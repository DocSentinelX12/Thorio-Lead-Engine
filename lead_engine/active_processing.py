"""Persistent handoffs for the qualification, verification, routing, and integrity chain."""
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


def airtable_integrity(agent: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    result = _airtable_integrity(agent, payload, ctx)
    lead = _lead(payload)
    fingerprint = lead["fingerprint"]
    # Integrity is the terminal persistence gate for the automated qualification
    # chain. Once durable synchronization is verified, record an audit task so
    # the system has an explicit post-route quality checkpoint. Outreach remains
    # separately authorization-gated and is never implicitly sent here.
    enqueue(ctx.db, "audit", {"lead": lead, "integrity_result": result, "routing_result": payload.get("routing_result", {})}, priority=4, dedupe_key=f"audit:{fingerprint}")
    result["handoff"] = "audit"
    return result
