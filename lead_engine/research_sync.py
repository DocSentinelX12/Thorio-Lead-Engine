from __future__ import annotations

import json
from typing import Any, Dict

from .airtable_sync import AirtableSyncError, _text, create_master_record, find_master_records, update_master_record

_RESEARCH_FIELD_MAP = {
    "Company Research": "company_research",
    "Decision Maker Research": "decision_maker_research",
    "Business Need Research": "business_need_research",
    "Current Intent Research": "current_intent_research",
    "Technical/Product/Hiring Research": "technical_product_hiring_research",
    "Commercial Research": "commercial_research",
    "Route Research": "route_research",
    "Evidence and Provenance": "evidence_events",
    "Closer Package": "closer_package",
    "Research Gaps and Unknowns": "research_gaps",
}

_RAW_RESEARCH_KEYS = {
    "company_research", "decision_maker_research", "business_need_research", "current_intent_research",
    "technical_product_hiring_research", "commercial_research", "route_research", "closer_package",
    "research_gaps", "research_status", "research_verified_fields", "research_sources", "research_timestamp",
    "research_completed_at", "evidence_events",
}


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _explicitly_verified(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("verified") is True:
        return True
    return str(value.get("verification_status") or value.get("status") or "").strip().lower() in {"verified", "research_verified"}


def _verified_fields(lead: Dict[str, Any]) -> list[str]:
    """Compute Airtable's verified-field list from explicit verification state only."""
    result: list[str] = []
    company = lead.get("company_research")
    if isinstance(company, dict) and company.get("company_verified") is True:
        result.append("company_verified")
    if isinstance(company, dict) and str(company.get("decision_maker_verification_status") or "").strip().lower() == "verified":
        result.append("decision_maker")
    for key in _RESEARCH_FIELD_MAP.values():
        if key in {"company_research", "evidence_events"}:
            continue
        if _explicitly_verified(lead.get(key)):
            result.append(key)
    return result


def _research_payload(lead: Dict[str, Any]) -> Dict[str, Any]:
    fingerprint = _text(lead.get("fingerprint"))
    company = _text(lead.get("company"))
    if not fingerprint:
        raise ValueError("Research synchronization requires a lead fingerprint.")
    if not company:
        raise ValueError("Research synchronization requires a company.")

    fields: Dict[str, Any] = {"Research Key": fingerprint, "Lead Fingerprint": fingerprint, "Company": company}
    status = _text(lead.get("research_status"))
    if status:
        fields["Research Status"] = status
    timestamp = _text(lead.get("research_completed_at")) or _text(lead.get("research_timestamp")) or _text(lead.get("researched_at"))
    if timestamp:
        fields["Research Timestamp"] = timestamp

    verified_text = _json_text(_verified_fields(lead))
    if verified_text is not None:
        fields["Verified Fields"] = verified_text

    for airtable_field, lead_key in _RESEARCH_FIELD_MAP.items():
        value = _json_text(lead.get(lead_key))
        if value is not None:
            fields[airtable_field] = value

    raw_package = _json_text(lead)
    if raw_package is None:
        raise ValueError("Research synchronization requires a serializable lead payload.")
    fields["Raw Research Package"] = raw_package
    return fields


def sync_research(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert the complete research-bearing lead payload without fabricating facts."""
    if not isinstance(lead, dict):
        raise ValueError("Research payload must be a dictionary.")
    fields = _research_payload(lead)
    key = fields["Research Key"]
    existing = find_master_records("research", "Research Key", key)
    if existing:
        record_id = _text(existing[0].get("id"))
        if not record_id:
            raise AirtableSyncError("Existing Research record has no Airtable record ID.")
        result = update_master_record("research", record_id, fields)
        records = result.get("records", [])
        if not records or not isinstance(records[0], dict):
            raise AirtableSyncError("Airtable returned no updated Research record.")
        return {"status": "updated", "record": records[0]}
    result = create_master_record("research", fields)
    records = result.get("records", [])
    if not records or not isinstance(records[0], dict):
        raise AirtableSyncError("Airtable returned no created Research record.")
    return {"status": "created", "record": records[0]}
