"""Persistent handoffs for the qualification, verification, routing, and revenue chain."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_queue import enqueue
from .agent_stateful_handlers import airtable_integrity as _airtable_integrity
from .agent_stateful_handlers import routing as _routing
from .agent_stateful_handlers import verification as _verification


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
    result = _verification(agent, payload, ctx)
    if result.get("verified") is True:
        lead = _lead(payload)
        enqueue(ctx.db, "routing", {"lead": lead, "verified": True}, priority=7, dedupe_key=f"routing:{lead['fingerprint']}")
        result["handoff"] = "routing"
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


def _sales_eligibility(lead: Mapping[str, Any], routing_result: Mapping[str, Any], integrity_result: Mapping[str, Any]) -> tuple[bool, str]:
    """Determine whether a verified opportunity may enter autonomous sales execution.

    Qualification and communication are deliberately separate. In particular,
    ``contact_communicated`` is an outcome of sales execution, never a
    prerequisite for entering it.
    """
    destinations = routing_result.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        return False, "no_supported_revenue_route"
    if bool(routing_result.get("review_required")):
        return False, "routing_requires_review"
    if not (lead.get("qualified") or lead.get("potential_routes")):
        return False, "not_qualified"
    research = lead.get("company_research")
    if not isinstance(research, Mapping):
        return False, "missing_company_research"
    if not research.get("decision_maker") or not research.get("decision_maker_evidence"):
        return False, "decision_maker_not_verified"
    contact_email = str(lead.get("contact_email") or research.get("decision_maker_email") or "").strip()
    if not contact_email:
        return False, "missing_contact_email"
    if integrity_result.get("sync_error_present"):
        # Airtable failure is a persistence retry condition, not a reason to
        # discard a qualified opportunity. The durable LeadDB record remains
        # authoritative while synchronization retries.
        return True, "airtable_sync_retryable"
    return True, "eligible"


def airtable_integrity(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _airtable_integrity(agent, payload, ctx)
    lead = _lead(payload)
    fingerprint = lead["fingerprint"]
    routing_result = payload.get("routing_result", {})
    if not isinstance(routing_result, Mapping):
        routing_result = {}

    eligible, eligibility_reason = _sales_eligibility(lead, routing_result, result)
    if eligible:
        updated = dict(lead)
        updated.update({
            "revenue_lifecycle_state": "sales_eligible",
            "sales_eligibility": "eligible",
            "sales_eligibility_reason": eligibility_reason,
            "eligible_routes": list(routing_result.get("destinations", [])),
            "preserved_routes": list(routing_result.get("destinations", [])),
        })
        stored = ctx.db.update_payload(fingerprint, updated) or updated
        enqueue(
            ctx.db,
            "outreach_closer",
            {"lead": stored, "routing_result": dict(routing_result), "integrity_result": dict(result)},
            priority=10,
            dedupe_key=f"sales:{fingerprint}",
        )
        result["sales_eligibility"] = "eligible"
        result["sales_eligibility_reason"] = eligibility_reason
        result["handoff"] = "outreach_closer"
    else:
        updated = dict(lead)
        if lead.get("qualified") or lead.get("potential_routes"):
            updated.update({
                "revenue_lifecycle_state": "qualified",
                "sales_eligibility": "blocked",
                "sales_eligibility_reason": eligibility_reason,
            })
            ctx.db.update_payload(fingerprint, updated)
        result["sales_eligibility"] = "blocked"
        result["sales_eligibility_reason"] = eligibility_reason
        result["handoff"] = "audit"

    enqueue(
        ctx.db,
        "audit",
        {"lead": ctx.db.get(fingerprint) or lead, "integrity_result": result, "routing_result": routing_result},
        priority=4,
        dedupe_key=f"audit:{fingerprint}",
    )
    return result
