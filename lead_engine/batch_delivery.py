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
    AirtableTransientError,
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
from .research_sync import sync_research
from .sales_handoff import package_is_ready

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
    """Upsert up to 10 records per Airtable request."""
    if not records:
        return []
    if len(records) > BATCH_SIZE:
        raise ValueError("Airtable batch upsert accepts at most 10 records")

    payload = {
        "performUpsert": {"fieldsToMergeOn": [merge_field]},
        "records": records,
        "typecast": True,
    }
    result = _request("PATCH", _master_table_url(table_key), payload)
    returned = result.get("records", [])
    if not isinstance(returned, list) or len(returned) != len(records):
        raise AirtableSyncError(
            f"Airtable batch upsert for {table_key} returned an unexpected record count."
        )
    return [record for record in returned if isinstance(record, dict)]


def _resilient_batch_upsert(
    table_key: str,
    merge_field: str,
    records: List[Dict[str, Any]],
) -> None:
    """Deliver a batch while isolating bad records without exploding requests."""
    if not records:
        return
    try:
        _batch_upsert(table_key, merge_field, records)
        return
    except AirtableTransientError:
        # Transport failures do not indicate bad records. Splitting the batch
        # would amplify an outage into many requests and exhaust the cycle.
        raise
    except Exception:
        if len(records) == 1:
            raise

    midpoint = max(1, len(records) // 2)
    _resilient_batch_upsert(table_key, merge_field, records[:midpoint])
    _resilient_batch_upsert(table_key, merge_field, records[midpoint:])


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
        "Website": str(lead.get("company_website") or "").strip() or None,
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
    """Synchronize only fully researched leads into the Airtable workspace."""
    if any(not package_is_ready(lead) for lead in leads):
        raise AirtableSyncError(
            "Raw or research-incomplete discoveries must remain in canonical storage; "
            "Airtable batch projection accepts only ready research packages."
        )
    for chunk in _chunks([
        {"fields": _lead_machine_fields(lead)} for lead in leads
    ]):
        _resilient_batch_upsert("lead_radar", "Duplicate Key", chunk)

    companies: Dict[str, Dict[str, Any]] = {}
    for lead in leads:
        company = str(lead.get("company") or "").strip()
        if company and company not in companies:
            companies[company] = {"fields": _company_fields(lead)}
    company_records = list(companies.values())
    for chunk in _chunks(company_records):
        _resilient_batch_upsert("companies", "Company", chunk)

    opportunities = _opportunity_records(leads)
    for chunk in _chunks(opportunities):
        _resilient_batch_upsert("opportunities", "Opportunity", chunk)


def sync_pending_batched(
    db,
    limit: int = 50,
    exclude_fingerprints: set[str] | frozenset[str] | None = None,
) -> Dict[str, Any]:
    """Synchronize pending leads with batch-first, durable delivery.

    Exclusions are scoped to one bounded drain cycle. Deferred leads remain
    durable and pending, but are not selected repeatedly within that same cycle.
    """
    excluded = {str(value).strip() for value in (exclude_fingerprints or ()) if str(value).strip()}
    valid: List[tuple[str, Dict[str, Any]]] = []
    failed: List[Dict[str, Any]] = []
    deferred_research: List[Dict[str, Any]] = []
    after_rowid = 0
    page_size = max(100, min(500, limit * 10))

    # Scan by stable rowid so deferring a page cannot shift offsets and skip
    # other records. This lets ready leads behind a large raw backlog proceed.
    while len(valid) < limit:
        rows = db.pending_scan(after_rowid=after_rowid, limit=page_size)
        if not rows:
            break
        deferred_page: List[tuple[str, Dict[str, Any]]] = []
        invalid_page: List[tuple[str, str]] = []
        for rowid, fingerprint, payload_json, _attempts in rows:
            after_rowid = int(rowid)
            if fingerprint in excluded:
                continue
            try:
                lead = json.loads(payload_json)
                if not isinstance(lead, dict):
                    raise ValueError("Stored lead payload must be an object.")
            except (TypeError, ValueError) as exc:
                invalid_page.append((fingerprint, f"Invalid stored lead payload: {exc}"))
                continue
            if not package_is_ready(lead):
                deferred_page.append((fingerprint, lead))
                deferred_research.append({
                    "status": "deferred_research",
                    "lead": lead,
                    "airtable_record": None,
                    "research_record": None,
                    "error": None,
                    "reason": "research_verification_pending",
                })
                continue
            valid.append((fingerprint, lead))
            if len(valid) >= limit:
                break
        if deferred_page:
            with db.batch_writes():
                for fingerprint, _lead in deferred_page:
                    db.defer_sync(fingerprint, "research_verification_pending")
        for fingerprint, error in invalid_page:
            db.mark_error(fingerprint, error)
            failed.append({"status": "failed", "lead": {}, "error": error})
        if len(valid) >= limit or len(rows) < page_size:
            break

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []

    for start in range(0, len(valid), BATCH_SIZE):
        chunk = valid[start:start + BATCH_SIZE]
        ready_chunk: List[tuple[str, Dict[str, Any]]] = []
        for fingerprint, lead in chunk:
            if package_is_ready(lead):
                ready_chunk.append((fingerprint, lead))
            else:
                db.defer_sync(fingerprint, "research_verification_pending")
                deferred_research.append({
                    "status": "deferred_research",
                    "lead": lead,
                    "airtable_record": None,
                    "research_record": None,
                    "error": None,
                    "reason": "research_verification_pending",
                })
        if not ready_chunk:
            continue

        ready_leads = [lead for _fingerprint, lead in ready_chunk]
        try:
            _run_batch_high_volume_sync(ready_leads)
        except AirtableTransientError as batch_exc:
            # Do not fall back to one request per record after a transient
            # outage. Keep ready records pending for a later cycle.
            for fingerprint, lead in ready_chunk:
                message = str(batch_exc)
                db.mark_error(fingerprint, message)
                failed.append({"status": "failed", "lead": lead, "error": message})
            continue
        except Exception as batch_exc:
            # A batch-level failure falls back only for the same ready subset.
            # Raw discoveries never enter a per-record Airtable create path.
            from .sync_worker import sync_one
            for fingerprint, lead in ready_chunk:
                result = sync_one(lead, db=db)
                if result.get("status") == "deferred_research":
                    db.defer_sync(fingerprint, "research_verification_pending")
                    deferred_research.append(result)
                    continue
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

        from .sync_worker import sync_one
        for fingerprint, lead in ready_chunk:
            try:
                result = sync_one(lead, db=db)
                if result.get("status") == "deferred_research":
                    db.defer_sync(fingerprint, "research_verification_pending")
                    deferred_research.append(result)
                    continue
                if result.get("status") == "synced":
                    db.mark_synced(fingerprint)
                    synced.append(result)
                elif result.get("status") == "already_exists":
                    db.mark_synced(fingerprint)
                    already_exists.append(result)
                else:
                    error = result.get("error") or "Complete sales handoff confirmation failed."
                    db.mark_error(fingerprint, error)
                    failed.append({**result, "error": error})
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
        "deferred_research": deferred_research,
        "deferred_research_count": len(deferred_research),
        "batch_mode": True,
        "batch_size": BATCH_SIZE,
    }
