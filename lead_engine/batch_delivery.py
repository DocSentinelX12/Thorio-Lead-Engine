"""Bounded Airtable delivery for production lead batches.

The normal single-lead sync path remains the compatibility and retry fallback.
Production synchronization uses Airtable's multi-record upsert endpoint for the
high-volume Lead Radar, Companies, and Opportunities tables so one source cycle
does not turn into one HTTP request per discovered record.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from .airtable_sync import (
    AirtableSyncError,
    _master_table_url,
    _normalize_lead,
    _request,
)
from .master_tracker_sync import (
    _company_source,
    _opportunity_fields,
    _routes,
)
from .sync_worker import (
    _build_followup_payload,
    _build_outreach_payload,
    _followup_required,
    _outreach_ready,
)
from .airtable_sync import (
    sync_followup,
    sync_outreach,
    sync_paxus_referral_state,
)
from .master_tracker_sync import sync_commission
from .paxus_referral_adapter import lead_to_paxus_referral

BATCH_SIZE = 10


_HUMAN_CONTROLLED_LEAD_FIELDS = {
    "Review Status",
    "Qualified Lead?",
    "Contact Ready",
    "Referral Submitted?",
    "Budget Confirmed",
    "Need Confirmed",
    "Decision Maker Confirmed",
    "Timeline Confirmed",
    "Qualification Score",
    "Reason Not Qualified",
    "Thorio Outreach Ready",
    "Outreach Status",
    "Contact Method",
    "Referral / Opportunity ID",
    "Work Queue",
    "Notes",
    "Thorio Fit",
    "Thorio Plan Recommendation",
}


def _chunks(items: List[Dict[str, Any]], size: int = BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _clean_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _batch_upsert(
    table_key: str,
    merge_field: str,
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Upsert up to 10 records per Airtable request.

    Airtable's performUpsert endpoint combines lookup, create, and update into
    one request. We keep the 10-record API ceiling explicit and let the caller
    fall back to the durable single-record path if a batch is rejected.
    """
    if not records:
        return []
    if len(records) > BATCH_SIZE:
        raise ValueError("Airtable batch upsert accepts at most 10 records")

    payload = {
        "performUpsert": {"fieldsToMergeOn": [merge_field]},
        "records": records,
    }
    result = _request("PATCH", _master_table_url(table_key), payload)
    returned = result.get("records", [])
    if not isinstance(returned, list) or len(returned) != len(records):
        raise AirtableSyncError(
            f"Airtable batch upsert for {table_key} returned an unexpected record count."
        )
    return [record for record in returned if isinstance(record, dict)]


def _lead_machine_fields(lead: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_lead(lead)
    return {
        key: value
        for key, value in normalized.items()
        if key not in _HUMAN_CONTROLLED_LEAD_FIELDS
    }


def _company_fields(lead: Dict[str, Any]) -> Dict[str, Any]:
    company = str(lead.get("company") or "").strip()
    if not company:
        raise ValueError("Company synchronization requires a company.")
    return _clean_fields({
        "Company": company,
        "Website": str(lead.get("company_website") or lead.get("url") or "").strip() or None,
        "Industry": str(lead.get("industry") or "").strip() or None,
        "Decision Maker": str(lead.get("person") or lead.get("contact_name") or "").strip() or None,
        "Title": str(lead.get("contact_title") or "").strip() or None,
        "Email": str(lead.get("contact_email") or "").strip() or None,
        "Phone": str(lead.get("contact_phone") or "").strip() or None,
        "LinkedIn / X": str(lead.get("linkedin_url") or lead.get("x_url") or "").strip() or None,
        "Source": _company_source(lead),
        "Notes": str(lead.get("notes") or "").strip() or None,
    })


def _opportunity_records(leads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for lead in leads:
        if lead.get("qualified") is not True:
            continue
        for route in _routes(lead):
            if route == "Thorio":
                continue
            fingerprint = str(lead.get("fingerprint") or "").strip()
            key = f"{fingerprint}:{route}"
            if not fingerprint or key in seen:
                continue
            seen.add(key)
            records.append({"fields": _clean_fields(_opportunity_fields(lead, route))})
    return records


def _run_batch_high_volume_sync(leads: List[Dict[str, Any]]) -> None:
    """Synchronize the high-volume tables in bounded batches."""
    for chunk in _chunks([
        {"fields": _lead_machine_fields(lead)} for lead in leads
    ]):
        _batch_upsert("lead_radar", "Duplicate Key", chunk)

    companies: Dict[str, Dict[str, Any]] = {}
    for lead in leads:
        company = str(lead.get("company") or "").strip()
        if company and company not in companies:
            companies[company] = {"fields": _company_fields(lead)}
    company_records = list(companies.values())
    for chunk in _chunks(company_records):
        _batch_upsert("companies", "Company", chunk)

    opportunities = _opportunity_records(leads)
    for chunk in _chunks(opportunities):
        _batch_upsert("opportunities", "Opportunity", chunk)


def sync_pending_batched(db, limit: int = 50) -> Dict[str, Any]:
    """Synchronize pending leads with batch-first, durable delivery.

    High-volume tables are sent in 10-record upserts. Route-specific lifecycle
    records remain on the existing single-record adapters because they are
    lower-volume and have stricter state transitions. A failed batch never marks
    local state as synced; the affected records are retried individually so no
    data is lost merely because a batch request was rejected.
    """
    rows = db.pending(limit=limit)
    valid: List[tuple[str, Dict[str, Any]]] = []
    failed: List[Dict[str, Any]] = []

    for fingerprint, payload_json, _attempts in rows:
        try:
            lead = json.loads(payload_json)
        except (TypeError, ValueError) as exc:
            message = f"Invalid stored lead payload: {exc}"
            db.mark_error(fingerprint, message)
            failed.append({"status": "failed", "lead": {}, "error": message})
            continue
        if not isinstance(lead, dict):
            message = "Invalid stored lead payload: expected an object."
            db.mark_error(fingerprint, message)
            failed.append({"status": "failed", "lead": {}, "error": message})
            continue
        valid.append((fingerprint, lead))

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []

    for start in range(0, len(valid), BATCH_SIZE):
        chunk = valid[start:start + BATCH_SIZE]
        leads = [lead for _fingerprint, lead in chunk]
        try:
            _run_batch_high_volume_sync(leads)
        except Exception as batch_exc:
            # Preserve the existing durable single-record path as the fallback.
            from .sync_worker import sync_one
            for fingerprint, lead in chunk:
                result = sync_one(lead)
                if result.get("status") in {"synced", "already_exists"}:
                    db.mark_synced(fingerprint)
                    if result.get("status") == "already_exists":
                        already_exists.append(result)
                    else:
                        synced.append(result)
                else:
                    error = result.get("error") or str(batch_exc)
                    db.mark_error(fingerprint, error)
                    failed.append({**result, "error": error})
            continue

        # High-volume tables are durable at this point. Finish lower-volume
        # lifecycle state per lead, retaining the established state-machine rules.
        from .sync_worker import sync_one
        for fingerprint, lead in chunk:
            try:
                if _outreach_ready(lead):
                    outreach_result = sync_outreach(_build_outreach_payload(lead))
                    if outreach_result.get("status") not in {"created", "updated", "synced", "already_exists"}:
                        raise AirtableSyncError(outreach_result.get("error") or "Outreach synchronization failed")
                    if _followup_required(lead):
                        followup_result = sync_followup(_build_followup_payload(lead))
                        if followup_result.get("status") not in {"created", "updated", "synced", "already_exists"}:
                            raise AirtableSyncError(followup_result.get("error") or "Follow-up synchronization failed")

                referral = lead_to_paxus_referral(lead)
                if (
                    referral.referral_submitted
                    or referral.contact_consent
                    or referral.warm_referral_ready
                    or referral.paxus_accepted
                    or referral.introduction_made
                    or referral.placement_count > 0
                    or referral.client_payment_received
                    or referral.commission_due
                ):
                    referral_result = sync_paxus_referral_state(referral)
                    if referral_result.get("status") not in {"created", "updated", "synced", "already_exists"}:
                        raise AirtableSyncError(referral_result.get("error") or "Referral synchronization failed")

                commission_result = sync_commission(lead)
                if commission_result is not None and commission_result.get("status") not in {"created", "updated", "synced", "already_exists"}:
                    raise AirtableSyncError(commission_result.get("error") or "Commission synchronization failed")

                db.mark_synced(fingerprint)
                synced.append({
                    "status": "synced",
                    "lead": lead,
                    "airtable_record": None,
                    "error": None,
                })
            except Exception as exc:
                db.mark_error(fingerprint, str(exc))
                failed.append({"status": "failed", "lead": lead, "error": str(exc)})

    return {
        "synced": synced,
        "already_exists": already_exists,
        "failed": failed,
        "synced_count": len(synced),
        "already_exists_count": len(already_exists),
        "failed_count": len(failed),
        "batch_mode": True,
        "batch_size": BATCH_SIZE,
    }
