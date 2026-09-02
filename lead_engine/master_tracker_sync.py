from __future__ import annotations

from typing import Any, Dict, List, Optional

from .airtable_sync import (
    AirtableSyncError,
    create_master_record,
    find_master_records,
    update_master_record,
)
from .paxus_referral_adapter import (
    lead_to_paxus_referral,
    paxus_commission_tracking_enabled,
)


MASTER_TRACKER_TABLE_KEYS = (
    "lead_radar",
    "companies",
    "opportunities",
    "outreach",
    "referrals",
    "followups",
    "commissions",
    "lead_sources",
)


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _clean_fields(
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        key: value
        for key, value in fields.items()
        if value is not None
    }


def _first_record(
    records: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not records:
        return None

    record = records[0]

    if not isinstance(record, dict):
        return None

    return record


def _upsert(
    table_key: str,
    lookup_field: str,
    lookup_value: Any,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    lookup_value = _text(lookup_value)

    if not lookup_value:
        raise ValueError(
            f"{table_key} synchronization requires "
            f"a value for {lookup_field}."
        )

    clean_fields = _clean_fields(fields)

    existing = find_master_records(
        table_key,
        lookup_field,
        lookup_value,
    )

    existing_record = _first_record(existing)

    if existing_record is not None:
        record_id = _text(
            existing_record.get("id")
        )

        if not record_id:
            raise AirtableSyncError(
                f"Existing {table_key} record has no Airtable record ID."
            )

        result = update_master_record(
            table_key,
            record_id,
            clean_fields,
        )

        records = result.get(
            "records",
            [],
        )

        record = _first_record(records)

        if record is None:
            raise AirtableSyncError(
                f"Airtable returned no updated record for {table_key}."
            )

        return {
            "status": "updated",
            "record": record,
        }

    result = create_master_record(
        table_key,
        clean_fields,
    )

    records = result.get(
        "records",
        [],
    )

    record = _first_record(records)

    if record is None:
        raise AirtableSyncError(
            f"Airtable returned no created record for {table_key}."
        )

    return {
        "status": "created",
        "record": record,
    }


def _routes(
    lead: Dict[str, Any],
) -> List[str]:
    value = lead.get(
        "potential_routes",
        [],
    )

    if isinstance(value, str):
        value = [value]

    if not isinstance(
        value,
        (list, tuple, set),
    ):
        return []

    allowed = {
        "Paxus",
        "Shiftr",
        "Thorio",
    }

    result: List[str] = []

    for route in value:
        normalized = _text(route)

        if (
            normalized in allowed
            and normalized not in result
        ):
            result.append(normalized)

    return result


def _opportunity_key(
    lead: Dict[str, Any],
    route: str,
) -> str:
    fingerprint = _text(
        lead.get("fingerprint")
    )

    if not fingerprint:
        raise ValueError(
            "Opportunity synchronization requires a fingerprint."
        )

    return f"{fingerprint}:{route}"


def sync_company(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    company = _text(
        lead.get("company")
    )

    if not company:
        raise ValueError(
            "Company synchronization requires a company."
        )

    fields = {
        "Company": company,
        "Website": (
            _text(
                lead.get("company_website")
            )
            or _text(
                lead.get("url")
            )
            or None
        ),
        "Industry": (
            _text(
                lead.get("industry")
            )
            or None
        ),
        "Decision Maker": (
            _text(
                lead.get("person")
            )
            or _text(
                lead.get("contact_name")
            )
            or None
        ),
        "Title": (
            _text(
                lead.get("contact_title")
            )
            or None
        ),
        "Email": (
            _text(
                lead.get("contact_email")
            )
            or None
        ),
        "Phone": (
            _text(
                lead.get("contact_phone")
            )
            or None
        ),
        "LinkedIn / X": (
            _text(
                lead.get("linkedin_url")
            )
            or _text(
                lead.get("x_url")
            )
            or None
        ),
        "Source": (
            _text(
                lead.get("source")
            )
            or None
        ),
        "Notes": (
            _text(
                lead.get("notes")
            )
            or None
        ),
    }

    return _upsert(
        "companies",
        "Company",
        company,
        fields,
    )


def _opportunity_fields(
    lead: Dict[str, Any],
    route: str,
) -> Dict[str, Any]:
    fingerprint = _text(
        lead.get("fingerprint")
    )

    company = _text(
        lead.get("company")
    )

    opportunity_key = _opportunity_key(
        lead,
        route,
    )

    return {
        "Opportunity": opportunity_key,
        "Company": company,
        "Partner": route,
        "Need": (
            _text(
                lead.get("signal")
            )
            or _text(
                lead.get("evidence")
            )
            or None
        ),
        "Stage": (
            _text(
                lead.get("opportunity_stage")
            )
            or (
                "Qualified"
                if lead.get("qualified") is True
                else "Review"
            )
        ),
        "Priority": (
            _text(
                lead.get("priority")
            )
            or None
        ),
        "Estimated Value": lead.get(
            "estimated_value"
        ),
        "Referral Date": (
            _text(
                lead.get("submitted_at")
            )[:10]
            if lead.get("submitted_at")
            else None
        ),
        "Next Follow-up": (
            _text(
                lead.get("next_action_date")
            )[:10]
            if lead.get("next_action_date")
            else None
        ),
        "Referral Confirmed": (
            bool(
                lead.get("paxus_accepted")
            )
            if route == "Paxus"
            else bool(
                lead.get("partner_confirmed")
            )
        ),
        "Partner Contact": (
            _text(
                lead.get("partner_contact")
            )
            or None
        ),
        "Notes": (
            (
                f"Lead fingerprint: {fingerprint}"
                if fingerprint
                else None
            )
        ),
    }


def sync_opportunities(
    lead: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    if lead.get("qualified") is not True:
        return []

    results: List[Dict[str, Any]] = []

    for route in _routes(lead):
        opportunity_key = _opportunity_key(
            lead,
            route,
        )

        results.append(
            _upsert(
                "opportunities",
                "Opportunity",
                opportunity_key,
                _opportunity_fields(
                    lead,
                    route,
                ),
            )
        )

    return results


def sync_lead_source(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    fingerprint = _text(
        lead.get("fingerprint")
    )

    source_url = _text(
        lead.get("url")
    )

    source = _text(
        lead.get("source")
    )

    if not fingerprint:
        raise ValueError(
            "Lead source synchronization requires a fingerprint."
        )

    source_key = (
        f"{fingerprint}:{source_url or source}"
    )

    fields = {
        "Lead": fingerprint,
        "Source": source or None,
        "Source URL": source_url or None,
        "Source Type": (
            _text(
                lead.get("source_type")
            )
            or None
        ),
        "Discovered Date": (
            _text(
                lead.get("discovered_at")
            )[:10]
            if lead.get("discovered_at")
            else None
        ),
        "Signal": (
            _text(
                lead.get("signal")
            )
            or None
        ),
        "Evidence": (
            _text(
                lead.get("evidence")
            )
            or None
        ),
        "Status": (
            _text(
                lead.get("evidence_status")
            )
            or None
        ),
    }

    return _upsert(
        "lead_sources",
        "Lead",
        source_key,
        {
            **fields,
            "Lead": source_key,
        },
    )


def sync_commission(
    lead: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    if not paxus_commission_tracking_enabled(
        lead
    ):
        return None

    referral = lead_to_paxus_referral(
        lead
    )

    fingerprint = _text(
        referral.fingerprint
    )

    if not fingerprint:
        raise ValueError(
            "Commission synchronization requires a fingerprint."
        )

    referral_key = (
        _text(
            referral.referral_id
        )
        or fingerprint
    )

    commission_key = (
        f"{fingerprint}:{referral_key}"
    )

    placement_value = lead.get(
        "placement_value"
    )

    commission_rate = 0.25

    expected_commission = lead.get(
        "expected_commission"
    )

    if (
        expected_commission is None
        and placement_value is not None
    ):
        try:
            expected_commission = (
                float(placement_value)
                * commission_rate
            )
        except (
            TypeError,
            ValueError,
        ):
            expected_commission = None

    fields = {
        "Company": _text(
            referral.company
        ),
        "Referral": referral_key,
        "Partner": "Paxus",
        "Deal / Placement Value": placement_value,
        "Commission Rate": commission_rate,
        "Expected Commission": expected_commission,
        "Eligible / Trigger Date": (
            _text(
                lead.get("payment_received_at")
            )[:10]
            if lead.get("payment_received_at")
            else None
        ),
        "Expected Payment Date": (
            _text(
                lead.get("expected_payment_date")
            )[:10]
            if lead.get("expected_payment_date")
            else None
        ),
        "Paid": bool(
            lead.get("paid")
        ),
        "Actual Amount": lead.get(
            "actual_payment"
        ),
        "Payment Date": (
            _text(
                lead.get("payment_date")
            )[:10]
            if lead.get("payment_date")
            else None
        ),
        "Payment Method": (
            _text(
                lead.get("payment_method")
            )
            or None
        ),
        "Notes": (
            _text(
                lead.get("notes")
            )
            or None
        ),
    }

    return _upsert(
        "commissions",
        "Referral",
        commission_key,
        {
            **fields,
            "Referral": commission_key,
        },
    )


def sync_master_tracker(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Synchronize the non-Lead-Radar portions of the
    eight-table Master Tracker.

    Lead Radar itself remains owned by the existing
    sync_lead_if_missing() path.

    Routing rules remain separate from storage.
    Paxus commission tracking is gated by the existing
    Paxus domain adapter.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    company_result = sync_company(
        lead
    )

    opportunity_results = sync_opportunities(
        lead
    )

    source_result = sync_lead_source(
        lead
    )

    commission_result = sync_commission(
        lead
    )

    return {
        "company": company_result,
        "opportunities": opportunity_results,
        "lead_source": source_result,
        "commission": commission_result,
  }
