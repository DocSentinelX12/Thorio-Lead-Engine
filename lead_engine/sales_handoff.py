"""Canonical pre-outreach package identity and Airtable handoff verification."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .research_package import research_readiness

PACKAGE_KEYS = (
    "fingerprint",
    "company",
    "company_website",
    "source",
    "source_id",
    "url",
    "person",
    "contact_name",
    "contact_title",
    "contact_email",
    "contact_phone",
    "linkedin_url",
    "x_url",
    "signal",
    "evidence",
    "business_need",
    "need_at",
    "current_need",
    "current_need_at",
    "inquiry_at",
    "last_inquiry_at",
    "intent_at",
    "discovery_timestamp",
    "qualified",
    "qualification_status",
    "qualification",
    "qualification_results",
    "reason_not_qualified",
    "route",
    "potential_routes",
    "eligible_routes",
    "preserved_routes",
    "routing_result",
    "dedupe_result",
    "opportunity_resolution",
    "company_research",
    "decision_maker_research",
    "business_need_research",
    "current_intent_research",
    "technical_product_hiring_research",
    "commercial_research",
    "route_research",
    "research_sources",
    "research_timestamp",
    "research_completed_at",
    "research_verified_fields",
    "evidence_events",
    "research_gaps",
    "closer_package",
    "outreach_context",
    "outreach_channel",
)

def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return value

def package_projection(lead: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _canonical(lead.get(key)) for key in PACKAGE_KEYS if key in lead}

def package_digest(lead: Mapping[str, Any]) -> str:
    payload = json.dumps(package_projection(lead), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def package_is_ready(lead: Mapping[str, Any]) -> bool:
    readiness = research_readiness(lead)
    return bool(readiness.get("ready"))

def _record_fields(record: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = record.get("fields", {})
    return fields if isinstance(fields, Mapping) else {}

def verify_lead_radar_record(record: Mapping[str, Any], lead: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping):
        return False
    fields = _record_fields(record)
    return (
        str(record.get("id") or "").strip()
        and str(fields.get("Duplicate Key") or "").strip() == str(lead.get("fingerprint") or "").strip()
        and str(fields.get("Company") or "").strip() == str(lead.get("company") or "").strip()
    )

def verify_research_record(record: Mapping[str, Any], lead: Mapping[str, Any], expected_digest: str) -> bool:
    if not isinstance(record, Mapping) or not str(record.get("id") or "").strip():
        return False
    fields = _record_fields(record)
    if str(fields.get("Research Key") or "").strip() != str(lead.get("fingerprint") or "").strip():
        return False
    if str(fields.get("Lead Fingerprint") or "").strip() != str(lead.get("fingerprint") or "").strip():
        return False
    raw = fields.get("Raw Research Package")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if not isinstance(stored, Mapping):
        return False
    if str(stored.get("__thorio_package_digest") or "").strip() != expected_digest:
        return False
    return package_digest(stored) == expected_digest

def verify_master_tracker(result: Mapping[str, Any], lead: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping) or result.get("status") != "synced":
        return False
    company_result = result.get("company")
    if not isinstance(company_result, Mapping) or not isinstance(company_result.get("record"), Mapping):
        return False
    company_record = company_result["record"]
    company_fields = _record_fields(company_record)
    if not str(company_record.get("id") or "").strip():
        return False
    if str(company_fields.get("Company") or "").strip() != str(lead.get("company") or "").strip():
        return False
    routes = lead.get("potential_routes") or []
    opportunities = result.get("opportunities") or []
    opportunity_count = len(opportunities) if isinstance(opportunities, list) else 0
    expected_opportunities = len([route for route in routes if str(route).strip() in {"Paxus", "Shiftr"}])
    return opportunity_count >= expected_opportunities

def verify_airtable_handoff(result: Mapping[str, Any], lead: Mapping[str, Any], expected_digest: str | None = None) -> tuple[bool, str]:
    if not package_is_ready(lead):
        return False, "research_package_not_ready"
    digest = expected_digest or package_digest(lead)
    if not verify_lead_radar_record(result.get("airtable_record"), lead):
        return False, "lead_radar_record_not_confirmed"
    if not verify_research_record(result.get("research_record"), lead, digest):
        return False, "research_record_package_mismatch"
    if not verify_master_tracker(result.get("master_tracker"), lead):
        return False, "master_tracker_not_confirmed"
    return True, digest
