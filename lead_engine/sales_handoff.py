"""Canonical pre-outreach package identity and Airtable handoff verification."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .research_package import research_readiness
from .lead_identity import validate_opportunity_identity
from .research_intelligence import validate_research_intelligence

PACKAGE_KEYS = (
    "opportunity_id", "fingerprint", "identity_version", "identity_derivation", "company", "company_website", "source", "source_id", "url", "person", "contact_name", "contact_title", "contact_email", "contact_phone", "linkedin_url", "x_url", "signal", "evidence", "business_need", "need_at", "current_need", "current_need_at", "inquiry_at", "last_inquiry_at", "intent_at", "discovery_timestamp", "qualified", "qualification_status", "qualification", "qualification_results", "reason_not_qualified", "route", "potential_routes", "eligible_routes", "preserved_routes", "routing_result", "dedupe_result", "opportunity_resolution", "company_research", "decision_maker_research", "business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research", "route_research", "research_sources", "research_timestamp", "research_completed_at", "research_verified_fields", "evidence_events", "research_gaps", "closer_package", "research_intelligence", "outreach_context", "outreach_channel",
)

def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping): return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)): return [_canonical(item) for item in value]
    if isinstance(value, set): return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return value

def _require_materialized_intelligence(lead: Mapping[str, Any]) -> Mapping[str, Any]:
    intelligence = lead.get("research_intelligence")
    if not isinstance(intelligence, Mapping) or not intelligence: raise ValueError("Research intelligence requires an opportunity_id and complete researched intelligence.")
    opportunity_id = str(lead.get("opportunity_id") or lead.get("fingerprint") or "").strip()
    if not opportunity_id: raise ValueError("Research intelligence requires an opportunity_id.")
    validate_research_intelligence(intelligence, opportunity_id=opportunity_id)
    graph = intelligence.get("evidence_graph"); claims = intelligence.get("claims")
    if not isinstance(graph, Mapping) or not isinstance(graph.get("nodes"), Mapping) or not graph["nodes"]: raise ValueError("Research intelligence requires non-empty researched evidence.")
    if not isinstance(claims, list) or not claims: raise ValueError("Research intelligence requires non-empty researched claims.")
    handoff = intelligence.get("handoff")
    if not isinstance(handoff, Mapping) or handoff.get("ready") is not True: raise ValueError("Research intelligence is not ready for handoff; additional research is required.")
    return intelligence

def package_projection(lead: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(lead)
    if candidate.get("fingerprint") or candidate.get("opportunity_id"): validate_opportunity_identity(candidate)
    _require_materialized_intelligence(candidate)
    return {key: _canonical(candidate.get(key)) for key in PACKAGE_KEYS if key in candidate}

def package_digest(lead: Mapping[str, Any]) -> str:
    payload = json.dumps(package_projection(lead), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def package_is_ready(lead: Mapping[str, Any]) -> bool:
    try:
        candidate = dict(lead); readiness = research_readiness(candidate); _require_materialized_intelligence(candidate)
    except (TypeError, ValueError, KeyError): return False
    routing_result = candidate.get("routing_result")
    destinations = routing_result.get("destinations") if isinstance(routing_result, Mapping) else None
    eligible_routes = candidate.get("eligible_routes"); preserved_routes = candidate.get("preserved_routes")
    return bool(readiness.get("ready") and isinstance(destinations, list) and bool(destinations) and isinstance(eligible_routes, list) and bool(eligible_routes) and isinstance(preserved_routes, list) and bool(preserved_routes))

def _record_fields(record: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = record.get("fields", {}); return fields if isinstance(fields, Mapping) else {}

def verify_lead_radar_record(record: Mapping[str, Any], lead: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping): return False
    try: validate_opportunity_identity(dict(lead))
    except ValueError: return False
    fields = _record_fields(record)
    return bool(str(record.get("id") or "").strip()) and str(fields.get("Duplicate Key") or "").strip() == str(lead.get("fingerprint") or "").strip() and str(fields.get("Company") or "").strip() == str(lead.get("company") or "").strip()

def verify_research_record(record: Mapping[str, Any], lead: Mapping[str, Any], expected_digest: str) -> bool:
    if not isinstance(record, Mapping) or not str(record.get("id") or "").strip(): return False
    try: validate_opportunity_identity(dict(lead)); _require_materialized_intelligence(lead)
    except ValueError: return False
    fields = _record_fields(record)
    if str(fields.get("Research Key") or "").strip() != str(lead.get("fingerprint") or "").strip(): return False
    if str(fields.get("Lead Fingerprint") or "").strip() != str(lead.get("fingerprint") or "").strip(): return False
    raw = fields.get("Raw Research Package")
    if not isinstance(raw, str) or not raw.strip(): return False
    try: stored = json.loads(raw)
    except (TypeError, ValueError): return False
    if not isinstance(stored, Mapping) or str(stored.get("__thorio_package_digest") or "").strip() != expected_digest: return False
    try: _require_materialized_intelligence(stored)
    except ValueError: return False
    return package_digest(stored) == expected_digest

def verify_master_tracker(result: Mapping[str, Any], lead: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping) or result.get("status") != "synced": return False
    company_result = result.get("company")
    if not isinstance(company_result, Mapping) or not isinstance(company_result.get("record"), Mapping): return False
    company_record = company_result["record"]; company_fields = _record_fields(company_record)
    if not str(company_record.get("id") or "").strip() or str(company_fields.get("Company") or "").strip() != str(lead.get("company") or "").strip(): return False
    routes = lead.get("potential_routes") or []; expected_routes = {str(route).strip() for route in routes if str(route).strip() in {"Paxus", "Shiftr"}}
    opportunities = result.get("opportunities")
    if not isinstance(opportunities, list): return not expected_routes
    observed_routes: dict[str, dict[str, Any]] = {}
    for item in opportunities:
        if not isinstance(item, Mapping): return False
        record = item.get("record")
        if not isinstance(record, Mapping) or not str(record.get("id") or "").strip(): return False
        fields = _record_fields(record); partner = str(fields.get("Partner") or "").strip(); opportunity = str(fields.get("Opportunity") or "").strip(); company = str(fields.get("Company") or "").strip(); expected_key = f"{lead.get('fingerprint', '').strip()}:{partner}" if partner else ""
        if partner not in {"Paxus", "Shiftr"} or partner in observed_routes or partner not in expected_routes or opportunity != expected_key or company != str(lead.get("company") or "").strip(): return False
        observed_routes[partner] = dict(record)
    return set(observed_routes) == expected_routes

def verify_airtable_handoff(result: Mapping[str, Any], lead: Mapping[str, Any], expected_digest: str | None = None) -> tuple[bool, str]:
    if not package_is_ready(lead): return False, "research_intelligence_not_ready"
    try: digest = expected_digest or package_digest(lead)
    except ValueError: return False, "research_intelligence_not_ready"
    if not verify_lead_radar_record(result.get("airtable_record"), lead): return False, "lead_radar_record_not_confirmed"
    if not verify_research_record(result.get("research_record"), lead, digest): return False, "research_record_package_mismatch"
    if not verify_master_tracker(result.get("master_tracker"), lead): return False, "master_tracker_not_confirmed"
    return True, digest
