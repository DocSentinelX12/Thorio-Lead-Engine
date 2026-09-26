from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, List, Optional

from .airtable_sync import AirtableSyncError, AIRTABLE_API_URL, _request, _text
from .config import LeadEngineConfig
from .sales_handoff import package_digest
from .lead_identity import validate_opportunity_identity\nfrom .research_intelligence import validate_research_intelligence

_RESEARCH_FIELD_MAP = {
    "Company Research": "company_research",
    "Decision Maker Research": "decision_maker_research",\n    "Research Intelligence": "research_intelligence",
    "Business Need Research": "business_need_research",
    "Current Intent Research": "current_intent_research",
    "Technical Product Hiring Research": "technical_product_hiring_research",
    "Commercial Research": "commercial_research",
    "Route Research": "route_research",
    "Evidence and Provenance": "evidence_events",
    "Closer Package": "closer_package",
    "Research Gaps and Unknowns": "research_gaps",
}

_RAW_RESEARCH_KEYS = {
    "company_research", "decision_maker_research", "research_intelligence", "business_need_research", "current_intent_research",
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
    if not fingerprint and not _text(lead.get("opportunity_id")):
        raise ValueError("Research synchronization requires a canonical opportunity identity (fingerprint or opportunity_id).")
    validate_opportunity_identity(dict(lead))
    fingerprint = fingerprint or _text(lead.get("opportunity_id"))
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

    raw_payload = dict(lead)
    raw_payload["opportunity_id"] = _text(lead.get("opportunity_id")) or fingerprint
    raw_payload["fingerprint"] = fingerprint
    raw_payload["__thorio_package_digest"] = package_digest(raw_payload)
    raw_package = _json_text(raw_payload)
    if raw_package is None:
        raise ValueError("Research synchronization requires a serializable lead payload.")
    fields["Raw Research Package"] = raw_package
    return fields


def _research_table_url() -> str:
    config = LeadEngineConfig.from_environment()
    table_name = _text(config.airtable_research_table)
    if not table_name:
        raise AirtableSyncError("No Airtable Research table configured.")
    base_id = _text(config.airtable_base_id)
    if not base_id:
        raise AirtableSyncError("AIRTABLE_BASE_ID must be configured.")
    return f"{AIRTABLE_API_URL}/{base_id}/{urllib.parse.quote(table_name, safe='')}"


def find_master_records(table_key: str, field_name: str, value: Any) -> List[Dict[str, Any]]:
    """Research-table lookup uses the dedicated Research table configuration."""
    if table_key != "research":
        raise AirtableSyncError(f"Research synchronization does not support table: {table_key}")
    if not _text(value):
        return []
    escaped = _text(value).replace("\\", "\\\\").replace('"', '\\"')
    field = _text(field_name)
    if not field:
        raise ValueError("Airtable lookup requires a field name.")
    formula = f'{{{field}}}="{escaped}"'
    records: List[Dict[str, Any]] = []
    offset: Optional[str] = None
    while True:
        params = {"filterByFormula": formula, "pageSize": "100"}
        if offset:
            params["offset"] = offset
        result = _request("GET", f"{_research_table_url()}?{urllib.parse.urlencode(params)}")
        page = result.get("records", [])
        if isinstance(page, list):
            records.extend(record for record in page if isinstance(record, dict))
        offset = result.get("offset")
        if not offset:
            return records


def create_master_record(table_key: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    if table_key != "research":
        raise AirtableSyncError(f"Research synchronization does not support table: {table_key}")
    if not isinstance(fields, dict):
        raise ValueError("Airtable record fields must be a dictionary.")
    return _request("POST", _research_table_url(), {"records": [{"fields": fields}]})


def update_master_record(table_key: str, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    if table_key != "research":
        raise AirtableSyncError(f"Research synchronization does not support table: {table_key}")
    record_id = _text(record_id)
    if not record_id:
        raise ValueError("Airtable update requires a record ID.")
    if not isinstance(fields, dict):
        raise ValueError("Airtable record fields must be a dictionary.")
    encoded_record_id = urllib.parse.quote(record_id, safe="")
    result = _request("PATCH", f"{_research_table_url()}/{encoded_record_id}", {"fields": fields})
    if "records" in result:
        return result
    return {"records": [result]}


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
