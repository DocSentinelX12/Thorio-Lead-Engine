"""Canonical pre-outreach package identity and Airtable handoff verification."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping
import urllib.parse

from .research_package import research_readiness
from .lead_identity import validate_materialized_opportunity_identity, validate_opportunity_identity
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
    validate_materialized_opportunity_identity(candidate)
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

def _record_id(record: Any) -> str:
    if not isinstance(record, Mapping):
        return ""
    return str(record.get("id") or "").strip()


def _read_airtable_record(table_key: str, record_id: str) -> Mapping[str, Any]:
    """Read one persisted record back from Airtable for production handoff verification."""
    record_id = str(record_id or "").strip()
    if not record_id:
        raise ValueError(f"Airtable readback requires a record ID for {table_key}.")
    from .airtable_sync import _master_table_url, _request
    if table_key == "research":
        from .research_sync import _research_table_url
        table_url = _research_table_url()
    else:
        table_url = _master_table_url(table_key)
    encoded = urllib.parse.quote(record_id, safe="")
    record = _request("GET", f"{table_url}/{encoded}")
    if not isinstance(record, Mapping):
        raise ValueError(f"Airtable returned an invalid {table_key} record for {record_id}.")
    return record


def reconstruct_airtable_handoff(result: Mapping[str, Any], *, readback: bool = True) -> dict[str, Any]:
    """Reconstruct the persisted handoff boundary from Airtable record IDs.

    Production verification reads the records back from Airtable rather than trusting
    the response objects returned by the preceding writes. Unit tests may explicitly
    disable readback because they do not have an Airtable boundary.
    """
    if not isinstance(result, Mapping):
        raise ValueError("Airtable handoff result must be an object.")

    def resolve(table_key: str, record: Any) -> Mapping[str, Any] | None:
        if not isinstance(record, Mapping):
            return None
        record_id = _record_id(record)
        if not record_id:
            raise ValueError(f"Airtable {table_key} result is missing its record ID.")
        return _read_airtable_record(table_key, record_id) if readback else record

    reconstructed: dict[str, Any] = {
        "airtable_record": resolve("lead_radar", result.get("airtable_record")),
        "research_record": resolve("research", result.get("research_record")),
        "master_tracker": result.get("master_tracker"),
        "referral_record": resolve("referrals", result.get("referral_record")),
        "outreach_record": resolve("outreach", result.get("outreach_record")),
        "followup_record": resolve("followups", result.get("followup_record")),
    }

    master = result.get("master_tracker")
    if isinstance(master, Mapping):
        master_copy = dict(master)
        company = master_copy.get("company")
        if isinstance(company, Mapping) and isinstance(company.get("record"), Mapping):
            master_copy["company"] = dict(company)
            master_copy["company"]["record"] = resolve("companies", company["record"])
        opportunities = master_copy.get("opportunities")
        if isinstance(opportunities, list):
            rebuilt = []
            for item in opportunities:
                if not isinstance(item, Mapping) or not isinstance(item.get("record"), Mapping):
                    raise ValueError("Master Tracker opportunity result is malformed.")
                rebuilt_item = dict(item)
                rebuilt_item["record"] = resolve("opportunities", item["record"])
                rebuilt.append(rebuilt_item)
            master_copy["opportunities"] = rebuilt
        astrivon_referral = master_copy.get("astrivon_referral")
        if isinstance(astrivon_referral, Mapping) and isinstance(astrivon_referral.get("record"), Mapping):
            master_copy["astrivon_referral"] = dict(astrivon_referral)
            master_copy["astrivon_referral"]["record"] = resolve("referrals", astrivon_referral["record"])
        astrivon_commissions = master_copy.get("astrivon_commissions")
        if isinstance(astrivon_commissions, list):
            rebuilt_commissions = []
            for item in astrivon_commissions:
                if not isinstance(item, Mapping) or not isinstance(item.get("record"), Mapping):
                    raise ValueError("Master Tracker commission result is malformed.")
                rebuilt_item = dict(item)
                rebuilt_item["record"] = resolve("commissions", item["record"])
                rebuilt_commissions.append(rebuilt_item)
            master_copy["astrivon_commissions"] = rebuilt_commissions
        commission = master_copy.get("commission")
        if isinstance(commission, Mapping) and isinstance(commission.get("record"), Mapping):
            master_copy["commission"] = dict(commission)
            master_copy["commission"]["record"] = resolve("commissions", commission["record"])
        reconstructed["master_tracker"] = master_copy

    return reconstructed


def _verify_optional_lifecycle_record(record: Any, lead: Mapping[str, Any], *, kind: str) -> bool:
    if record is None:
        return True
    if not isinstance(record, Mapping) or not _record_id(record):
        return False
    fields = _record_fields(record)
    fingerprint = str(lead.get("fingerprint") or "").strip()
    company = str(lead.get("company") or "").strip()
    if str(fields.get("Company") or "").strip() != company:
        return False
    if kind == "outreach":
        expected_prefix = fingerprint + ":"
        return str(fields.get("Outreach") or "").strip().startswith(expected_prefix) and str(fields.get("Opportunity") or "").strip().startswith(expected_prefix)
    if kind == "followup":
        expected_prefix = fingerprint + ":"
        return str(fields.get("Follow-up") or "").strip().startswith(expected_prefix) and str(fields.get("Opportunity") or "").strip().startswith(expected_prefix)
    return True


def verify_airtable_handoff(result: Mapping[str, Any], lead: Mapping[str, Any], expected_digest: str | None = None, *, readback: bool = True) -> tuple[bool, str]:
    if not package_is_ready(lead): return False, "research_intelligence_not_ready"
    try: digest = expected_digest or package_digest(lead)
    except ValueError: return False, "research_intelligence_not_ready"
    try:
        persisted = reconstruct_airtable_handoff(result, readback=readback)
    except (TypeError, ValueError, KeyError, Exception) as exc:
        return False, f"airtable_readback_failed:{exc}"
    if not verify_lead_radar_record(persisted.get("airtable_record"), lead): return False, "lead_radar_record_not_confirmed"
    if not verify_research_record(persisted.get("research_record"), lead, digest): return False, "research_record_package_mismatch"
    if not verify_master_tracker(persisted.get("master_tracker"), lead): return False, "master_tracker_not_confirmed"
    if not _verify_optional_lifecycle_record(persisted.get("outreach_record"), lead, kind="outreach"): return False, "outreach_record_not_confirmed"
    if not _verify_optional_lifecycle_record(persisted.get("followup_record"), lead, kind="followup"): return False, "followup_record_not_confirmed"
    referral = persisted.get("referral_record")
    if referral is not None:
        if not isinstance(referral, Mapping) or not _record_id(referral): return False, "referral_record_not_confirmed"
        fields = _record_fields(referral)
        if str(fields.get("Company") or "").strip() != str(lead.get("company") or "").strip(): return False, "referral_company_mismatch"
        if str(fields.get("Referral") or "").strip() != str(lead.get("fingerprint") or "").strip(): return False, "referral_fingerprint_mismatch"
    return True, digest
    if not package_is_ready(lead): return False, "research_intelligence_not_ready"
    try: digest = expected_digest or package_digest(lead)
    except ValueError: return False, "research_intelligence_not_ready"
    if not verify_lead_radar_record(result.get("airtable_record"), lead): return False, "lead_radar_record_not_confirmed"
    if not verify_research_record(result.get("research_record"), lead, digest): return False, "research_record_package_mismatch"
    if not verify_master_tracker(result.get("master_tracker"), lead): return False, "master_tracker_not_confirmed"
    return True, digest
