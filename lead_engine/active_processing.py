"""Persistent handoffs for the qualification, verification, routing, and revenue chain."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_queue import enqueue
from .agent_stateful_handlers import airtable_integrity as _airtable_integrity
from .agent_stateful_handlers import routing as _routing
from .agent_stateful_handlers import verification as _verification
from .dedupe import Dedupe


def _lead(payload: Mapping[str, Any]) -> Dict[str, Any]:
    lead = payload.get("lead", payload)
    if not isinstance(lead, Mapping):
        raise ValueError("lead must be a mapping")
    value = dict(lead)
    if not str(value.get("fingerprint") or "").strip():
        raise ValueError("lead requires fingerprint")
    return value


def priority(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    lead = _lead(payload)
    evidence = sum(1 for key in ("signal", "evidence", "job_title", "person", "company") if str(lead.get(key) or "").strip())
    qualified = bool(lead.get("qualified") or lead.get("potential_routes"))
    freshness = bool(lead.get("need_at") or lead.get("current_need_at") or lead.get("inquiry_at") or lead.get("last_inquiry_at") or lead.get("intent_at") or lead.get("discovery_timestamp"))
    research_ready = str(lead.get("research_status") or "").strip().lower() == "complete"
    decision_maker_ready = bool(lead.get("company_research", {}).get("decision_maker")) if isinstance(lead.get("company_research"), Mapping) else False
    score = evidence + (5 if qualified else 0) + (3 if freshness else 0) + (2 if research_ready else 0) + (1 if decision_maker_ready else 0)
    fingerprint = lead["fingerprint"]
    enqueue(ctx.db, "verification", {"lead": lead, "evidence_events": payload.get("evidence_events", [])}, priority=8, dedupe_key=f"verification:{fingerprint}")
    return {"role": agent, "priority_score": score, "lead": lead, "research_ready": research_ready, "decision_maker_ready": decision_maker_ready, "actionability": "ready" if research_ready and decision_maker_ready else "research_required", "handoff": "verification"}


def verification(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    lead = _lead(payload)
    fingerprint = lead["fingerprint"]
    validation_lead = dict(lead)
    if not str(validation_lead.get("route") or "").strip():
        potential_routes = validation_lead.get("potential_routes")
        if isinstance(potential_routes, list) and potential_routes:
            validation_lead["route"] = str(potential_routes[0])
    verification_payload = dict(payload)
    verification_payload["lead"] = validation_lead
    result = _verification(agent, verification_payload, ctx)

    if result.get("decision_maker_verification") == "verified":
        current_lead = ctx.db.get(fingerprint) or lead
        research = dict(current_lead.get("company_research") or {}) if isinstance(current_lead.get("company_research"), Mapping) else {}
        research["decision_maker_verification_status"] = "verified"
        if result.get("decision_maker_role_evidence"):
            research["decision_maker_role_evidence"] = result["decision_maker_role_evidence"]
        updated = dict(current_lead)
        updated["company_research"] = research
        updated["research_status"] = "complete"
        stored = ctx.db.update_payload(fingerprint, updated) or updated
        enqueue(ctx.db, "qualification_a", {"lead": stored, "evidence_events": payload.get("evidence_events", []), "research_result": {"status": "complete", "verified_fields": stored.get("research_verified_fields", [])}}, priority=9, dedupe_key=f"qualification_a_verified:{fingerprint}")
        result["decision_maker_handoff"] = "qualification_a"
        result["lead"] = stored

    if result.get("verified") is True:
        enqueue(ctx.db, "routing", {"lead": ctx.db.get(fingerprint) or lead, "verified": True}, priority=7, dedupe_key=f"routing:{fingerprint}")
        result["handoff"] = "routing"
    elif result.get("decision_maker_verification") == "verified":
        result["handoff"] = "qualification_a"
    else:
        result["handoff"] = "review_required"
    return result


def routing(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _routing(agent, payload, ctx)
    lead = _lead(payload)
    if result.get("destinations"):
        enqueue(ctx.db, "airtable_integrity", {"lead": lead, "routing_result": result}, priority=6, dedupe_key=f"airtable_integrity:{lead['fingerprint']}")
    result["handoff"] = "airtable_integrity" if result.get("destinations") else "review_required"
    return result


def _sales_eligibility(lead: Mapping[str, Any], routing_result: Mapping[str, Any], integrity_result: Mapping[str, Any], db: Any = None) -> tuple[bool, str]:
    """Determine whether a verified opportunity may enter autonomous sales execution.

    Qualification, exact-opportunity identification, and deduplication are
    upstream gates. Communication is deliberately downstream of qualification.
    """
    destinations = routing_result.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        return False, "no_supported_revenue_route"
    if bool(routing_result.get("review_required")):
        return False, "routing_requires_review"
    if lead.get("qualified") is not True:
        return False, "not_qualified"
    if not str(lead.get("business_need") or "").strip():
        return False, "missing_exact_opportunity"
    if db is not None:
        duplicate = Dedupe(db).find_exact_duplicate(dict(lead))
        if duplicate is not None:
            return False, "exact_duplicate"
    research = lead.get("company_research")
    if not isinstance(research, Mapping):
        return False, "missing_company_research"
    if not research.get("decision_maker") or not research.get("decision_maker_evidence"):
        return False, "decision_maker_not_verified"
    if str(research.get("decision_maker_verification_status") or "").strip().lower() != "verified":
        return False, "decision_maker_not_verified"
    contact_email = str(lead.get("contact_email") or research.get("decision_maker_email") or "").strip()
    if not contact_email:
        return False, "missing_contact_email"
    if integrity_result.get("sync_error_present"):
        return True, "airtable_sync_retryable"
    return True, "eligible"


def airtable_integrity(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _airtable_integrity(agent, payload, ctx)
    lead = _lead(payload)
    fingerprint = lead["fingerprint"]
    current_lead = ctx.db.get(fingerprint) or lead
    routing_result = payload.get("routing_result", {})
    if not isinstance(routing_result, Mapping):
        routing_result = {}

    eligible, eligibility_reason = _sales_eligibility(current_lead, routing_result, result, ctx.db)
    if eligible:
        already_active = bool(current_lead.get("last_outreach_action_id")) or str(current_lead.get("outreach_state") or "").lower() == "awaiting_response"
        updated = dict(current_lead)
        if not already_active:
            updated["revenue_lifecycle_state"] = "sales_eligible"
        updated.update({"sales_eligibility": "eligible", "sales_eligibility_reason": eligibility_reason, "eligible_routes": list(routing_result.get("destinations", [])), "preserved_routes": list(routing_result.get("destinations", []))})
        stored = ctx.db.update_payload(fingerprint, updated) or updated
        if not already_active:
            enqueue(ctx.db, "outreach_closer", {"lead": stored, "routing_result": dict(routing_result), "integrity_result": dict(result)}, priority=10, dedupe_key=f"sales:{fingerprint}")
            result["handoff"] = "outreach_closer"
        else:
            result["handoff"] = "outreach_already_active"
        result["sales_eligibility"] = "eligible"
        result["sales_eligibility_reason"] = eligibility_reason
    else:
        updated = dict(current_lead)
        if current_lead.get("qualified") is True:
            updated.update({"revenue_lifecycle_state": "qualified" if eligibility_reason not in {"exact_duplicate"} else "closed_lost", "sales_eligibility": "blocked", "sales_eligibility_reason": eligibility_reason})
            ctx.db.update_payload(fingerprint, updated)
        result["sales_eligibility"] = "blocked"
        result["sales_eligibility_reason"] = eligibility_reason
        result["handoff"] = "audit"

    enqueue(ctx.db, "audit", {"lead": ctx.db.get(fingerprint) or current_lead, "integrity_result": result, "routing_result": routing_result}, priority=4, dedupe_key=f"audit:{fingerprint}")
    return result