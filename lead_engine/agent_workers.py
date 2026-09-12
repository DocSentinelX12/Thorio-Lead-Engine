from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping

from .active_processing import airtable_integrity, routing, verification
from .advanced_agent_logic import advanced_handler_registry
from .agent_queue import claim, complete, enqueue, fail, heartbeat, retry
from .agent_specializations import AgentSpecialization, get_specialization
from .agent_stateful_handlers import identity_resolution
from .qualification import apply_company_qualification
from .research_queue import process_paxus_research_queue
from .outreach_engine import OutreachContractError, apply_outcome, build_outreach_decision, objection_response
from .revenue_conversation import objection_reply
from .revenue_execution import PRIVILEGED_CAPABILITY, RevenueTransportUnavailable, configured_revenue_transport, execute_outbound


class AgentContractError(ValueError):
    """Raised when a worker receives an invalid specialist task or result."""


@dataclass(frozen=True)
class AgentExecutionContext:
    db: Any
    worker_id: str
    revenue_transport: Any = None


@dataclass(frozen=True)
class AgentExecutionResult:
    agent: str
    task_id: str
    status: str
    result: Dict[str, Any]


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentContractError(f"{label} must be a mapping")
    return dict(value)


def _lead_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return _require_mapping(payload.get("lead", payload), "lead")


def _persist_lead(db: Any, lead: Dict[str, Any]) -> Dict[str, Any]:
    fingerprint = str(lead.get("fingerprint") or "").strip()
    if not fingerprint:
        raise AgentContractError("lead requires fingerprint for persistent processing")
    stored = db.update_payload(fingerprint, lead)
    if stored is None:
        raise AgentContractError(f"lead not found for persistent update: {fingerprint}")
    return stored


_DISCOVERY_SOURCE_ALIASES = {
    "x_signal": ("x", "twitter"), "threads_signal": ("threads",), "reddit_signal": ("reddit",),
    "linkedin_signal": ("linkedin",), "facebook_signal": ("facebook",), "instagram_signal": ("instagram",),
    "hacker_news_signal": ("hacker news", "hacker_news", "news.ycombinator.com", "hn"),
    "indie_hackers_signal": ("indie hackers", "indie_hackers", "indiehackers"),
    "product_hunt_signal": ("product hunt", "product_hunt", "producthunt"),
}


def _source_text(record: Mapping[str, Any]) -> str:
    return " ".join(str(record.get(key) or "").strip().lower() for key in ("source", "provider", "source_url", "url") if str(record.get(key) or "").strip())


def _discovery_handler_for(agent: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    record = _require_mapping(payload.get("record", payload), "record")
    source = _source_text(record)
    signal = str(record.get("signal") or record.get("evidence") or "").strip()
    if not signal:
        raise AgentContractError(f"{agent} requires observed signal/evidence")
    if agent in _DISCOVERY_SOURCE_ALIASES:
        if not any(alias in source for alias in _DISCOVERY_SOURCE_ALIASES[agent]):
            raise AgentContractError(f"{agent} received evidence outside its permanent source lane: {record.get('source')!r}")
    elif agent == "web_job_signal":
        markers = ("job", "jobs", "career", "careers", "hiring", "greenhouse", "lever", "workable", "ashby", "remote", "jobicy", "himalayas", "remote ok", "remotejobs", "arbeitnow", "muse")
        if not any(marker in source for marker in markers) and not any(key in record for key in ("job_title", "application_url", "apply_url")):
            raise AgentContractError(f"web_job_signal received evidence that is not identifiable as a job source: {record.get('source')!r}")
    fingerprint = str(record.get("fingerprint") or payload.get("fingerprint") or "").strip()
    lead = ctx.db.get(fingerprint) if fingerprint else None
    provenance = dict(record.get("provenance") or {}) if isinstance(record.get("provenance"), Mapping) else {}
    provenance.update({"collector_agent": agent, "source_lane": agent, "collected_at": datetime.now(timezone.utc).isoformat()})
    normalized = dict(record)
    normalized.update({"source_lane": agent, "observed": True, "qualification_performed": False, "provenance": provenance})
    if fingerprint and lead is not None:
        enqueue(ctx.db, "company_research", {"lead": dict(lead), "evidence_events": [normalized], "discovery_agent": agent}, priority=7, dedupe_key=f"company_research:{fingerprint}")
    return {"agent": agent, "role": "discovery", "source": record.get("source") or agent, "source_lane": agent, "record": normalized, "observed": True, "qualification_performed": False, "handoff": "company_research" if fingerprint and lead is not None else "awaiting_persistence", "provenance": provenance}


def _make_discovery_handler(agent: str) -> Callable[..., Dict[str, Any]]:
    def handler(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
        return _discovery_handler_for(agent, payload, ctx)
    handler.__name__ = f"_{agent}_handler"
    return handler


def _qualification_a(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    research_status = str(lead.get("research_status") or "").strip().lower()
    if research_status != "complete":
        raise AgentContractError("qualification_a requires completed company research")
    evaluated = _persist_lead(ctx.db, apply_company_qualification(lead))
    fingerprint = str(evaluated.get("fingerprint"))
    evidence_events = payload.get("evidence_events", [])
    paxus = (evaluated.get("qualification_results") or {}).get("Paxus", {})
    handoffs = ["qualification_b"]
    if paxus.get("qualified") and not paxus.get("true_referral"):
        enqueue(ctx.db, "paxus_research", {"lead": evaluated, "paxus_qualification": paxus}, priority=10, dedupe_key=f"paxus_research:{fingerprint}")
        handoffs.append("paxus_research")
    enqueue(ctx.db, "qualification_b", {"lead": evaluated, "prior_result": {"agent": "qualification_a", "qualified_companies": evaluated.get("potential_routes", [])}, "evidence_events": evidence_events, "research_result": {"status": research_status, "verified_fields": evaluated.get("research_verified_fields", [])}}, priority=9, dedupe_key=f"qualification_b:{fingerprint}")
    return {"role": "qualification_a", "lead": evaluated, "qualification_results": evaluated.get("qualification_results", {}), "qualified_companies": evaluated.get("potential_routes", []), "independent_review": "primary", "handoffs": handoffs}


def _qualification_b(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    research_status = str(lead.get("research_status") or "").strip().lower()
    if research_status != "complete":
        raise AgentContractError("qualification_b requires completed company research")
    evaluated = _persist_lead(ctx.db, apply_company_qualification(lead))
    fingerprint = str(evaluated.get("fingerprint"))
    enqueue(ctx.db, "priority", {"lead": evaluated, "evidence_events": payload.get("evidence_events", [])}, priority=5, dedupe_key=f"priority:{fingerprint}")
    return {"role": "qualification_b", "lead": evaluated, "qualification_results": evaluated.get("qualification_results", {}), "qualified_companies": evaluated.get("potential_routes", []), "independent_review": "validation", "challenged_prior_result": payload.get("prior_result") is not None}


def _company_research(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    research = payload.get("research")
    if research is not None and not isinstance(research, Mapping):
        raise AgentContractError("research must be a mapping when supplied")
    supplied = dict(research or {})
    fingerprint = str(lead.get("fingerprint") or "").strip()
    if not fingerprint:
        raise AgentContractError("company_research requires lead fingerprint")
    existing = lead.get("company_research") if isinstance(lead.get("company_research"), Mapping) else {}
    merged_research = {**dict(existing), **supplied} if supplied else dict(existing)
    if not merged_research:
        merged_research = {"company_verified": bool(lead.get("company")), "fabricated_fields": []}
        person = str(lead.get("person") or lead.get("contact_name") or "").strip()
        if person:
            merged_research["decision_maker"] = person
            merged_research["decision_maker_evidence"] = str(lead.get("evidence") or lead.get("signal") or "").strip()
            if merged_research["decision_maker_evidence"]:
                merged_research["decision_maker_verification_status"] = "observed_needs_role_verification"
    verified_fields = tuple(key for key, value in merged_research.items() if value not in (None, "", [], {}, ()))
    research_complete = bool(merged_research.get("company_verified") and merged_research.get("decision_maker") and merged_research.get("decision_maker_evidence") and str(merged_research.get("decision_maker_verification_status") or "").lower() == "verified")
    status = "complete" if research_complete else "research_required"
    merged = dict(lead)
    merged["company_research"] = merged_research
    merged["research_status"] = status
    merged["research_verified_fields"] = list(verified_fields)
    stored = _persist_lead(ctx.db, merged)
    handoff = None
    if status == "complete":
        enqueue(ctx.db, "qualification_a", {"lead": stored, "evidence_events": payload.get("evidence_events", []), "research_result": {"status": status, "verified_fields": list(verified_fields)}}, priority=9, dedupe_key=f"qualification_a:{fingerprint}")
        handoff = "qualification_a"
    return {"role": "company_research", "lead": stored, "research": merged_research, "research_status": status, "verified_fields": list(verified_fields), "decision_maker_verified": str(merged_research.get("decision_maker_verification_status") or "").lower() == "verified", "fabricated_fields": list(merged_research.get("fabricated_fields") or []), "handoff": handoff or "research_required"}


def _paxus_research(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    result = process_paxus_research_queue(ctx.db, limit=1)
    fingerprint = str(lead.get("fingerprint") or "").strip()
    refreshed = ctx.db.get(fingerprint) if fingerprint else lead
    refreshed = refreshed or lead
    paxus = (refreshed.get("qualification_results") or {}).get("Paxus", {})
    return {"role": "paxus_research", "lead": refreshed, "queue_result": result, "true_referral": bool(paxus.get("true_referral")), "research_status": refreshed.get("research_status", "research_required")}


def _duplicate_resolution(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes, Mapping)):
        raise AgentContractError("candidates must be a list-like collection")
    candidate_list = [dict(item) for item in candidates if isinstance(item, Mapping)]
    return {"role": "duplicate_resolution", "lead": lead, "candidate_count": len(candidate_list), "decision": payload.get("decision", "requires_identity_comparison"), "preserve_distinct_opportunities": True}


def _priority(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    evidence = sum(1 for key in ("signal", "evidence", "job_title", "person", "company") if str(lead.get(key) or "").strip())
    qualified = bool(lead.get("qualified") or lead.get("potential_routes"))
    freshness = bool(lead.get("need_at") or lead.get("current_need_at") or lead.get("inquiry_at") or lead.get("last_inquiry_at") or lead.get("intent_at"))
    research_ready = str(lead.get("research_status") or "").strip().lower() == "complete"
    decision_maker_ready = bool(lead.get("company_research", {}).get("decision_maker")) if isinstance(lead.get("company_research"), Mapping) else False
    score = evidence + (5 if qualified else 0) + (3 if freshness else 0) + (2 if research_ready else 0) + (1 if decision_maker_ready else 0)
    return {"role": "priority", "priority_score": score, "lead": lead, "research_ready": research_ready, "decision_maker_ready": decision_maker_ready, "actionability": "ready" if research_ready and decision_maker_ready else "research_required", "inputs_used": ["evidence", "qualification", "freshness", "research", "decision_maker"]}


def _outreach_closer(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    fingerprint = str(lead.get("fingerprint") or "").strip()
    if not fingerprint:
        raise AgentContractError("outreach_closer requires lead fingerprint")
    current = ctx.db.get(fingerprint)
    if isinstance(current, Mapping):
        current = dict(current)
        if current.get("last_outreach_action_id") or str(current.get("outreach_state") or "").lower() == "awaiting_response":
            return {"role": "outreach_closer", "lead": current, "autonomous": True, "approval_required": False, "action": "already_active", "delivery": dict(current.get("last_outreach_delivery") or {}), "action_id": current.get("last_outreach_action_id"), "conversation_id": current.get("conversation_id"), "next_state": current.get("outreach_state")}
        lead = current
    if str(lead.get("sales_eligibility") or "").strip().lower() != "eligible":
        raise AgentContractError("outreach_closer requires a sales-eligible opportunity")
    if str(lead.get("research_status") or "").strip().lower() != "complete":
        raise AgentContractError("outreach_closer requires completed company research")
    research = lead.get("company_research")
    if not isinstance(research, Mapping) or not research.get("decision_maker") or not research.get("decision_maker_evidence"):
        raise AgentContractError("outreach_closer requires verified decision-maker research")
    try:
        decision = build_outreach_decision(lead)
    except OutreachContractError as exc:
        raise AgentContractError(str(exc)) from exc
    route = str(decision.route or "").strip().lower()
    if not route:
        raise AgentContractError("outreach_closer requires a selected revenue route")
    conversation_id = str(lead.get("conversation_id") or f"conversation:{lead['fingerprint']}:{route}")
    transport = ctx.revenue_transport if ctx.revenue_transport is not None else configured_revenue_transport()
    action = execute_outbound(ctx.db, worker_capability=PRIVILEGED_CAPABILITY, opportunity_id=str(lead["fingerprint"]), conversation_id=conversation_id, channel=str(lead.get("outreach_channel") or "email"), recipient={"name": decision.contact_name, "email": decision.contact_email}, subject=decision.subject, body=decision.body, transport=transport, idempotency_key=f"outreach:{lead['fingerprint']}:{route}:{int(lead.get('outreach_attempt', 0) or 0) + 1}")
    updated = dict(lead)
    history = list(lead.get("outreach_history") or []) if isinstance(lead.get("outreach_history") or [], list) else []
    history.append({"action_id": action.action_id, "conversation_id": conversation_id, "route": route, "channel": action.channel, "status": action.status, "provider_result": dict(action.provider_result or {})})
    updated.update({"conversation_id": conversation_id, "revenue_lifecycle_state": "outreach_sent", "outreach_route": route, "outreach_state": "awaiting_response", "outreach_attempt": int(lead.get("outreach_attempt", 0) or 0) + 1, "next_follow_up_at": decision.next_follow_up_at, "follow_up_due": bool(decision.next_follow_up_at), "outreach_draft_subject": decision.subject, "outreach_draft_body": decision.body, "outreach_history": history, "last_outreach_action_id": action.action_id, "last_outreach_delivery": dict(action.provider_result or {})})
    stored = _persist_lead(ctx.db, updated)
    return {"role": "outreach_closer", "lead": stored, "autonomous": True, "approval_required": False, "action": "send_outreach", "route": route, "contact": {"name": decision.contact_name, "email": decision.contact_email}, "subject": decision.subject, "body": decision.body, "evidence_refs": list(decision.evidence_refs), "buying_signal": decision.buying_signal, "next_state": "awaiting_response", "next_follow_up_at": decision.next_follow_up_at, "stop_reason": decision.stop_reason, "delivery": dict(action.provider_result or {}), "action_id": action.action_id, "conversation_id": conversation_id, "truthfulness_guard": "evidence_only"}


def _follow_up(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    fingerprint = str(lead.get("fingerprint") or "").strip()
    if not fingerprint:
        raise AgentContractError("follow_up requires lead fingerprint")
    snapshot = dict(lead)
    current = ctx.db.get(fingerprint)
    if current is None:
        raise AgentContractError(f"follow_up lead not found: {fingerprint}")
    lead = dict(current)
    task_event_id = str(payload.get("inbound_event_id") or "").strip()
    if task_event_id:
        events = lead.get("conversation_events")
        latest_event_id = ""
        if isinstance(events, list) and events and isinstance(events[-1], Mapping):
            latest_event_id = str(events[-1].get("event_id") or "").strip()
        if latest_event_id and latest_event_id != task_event_id:
            return {"role": "follow_up", "lead": lead, "autonomous": True, "approval_required": False, "outreach_state": lead.get("outreach_state"), "next_follow_up_at": lead.get("next_follow_up_at"), "stop_reason": lead.get("outreach_stop_reason"), "action": "superseded", "outcome_recorded": False}
    outcome = str(payload.get("outcome") or lead.get("outreach_state") or "no_response").strip().lower()
    if outcome == "no_response" and snapshot.get("next_follow_up_at") != lead.get("next_follow_up_at"):
        return {"role": "follow_up", "lead": lead, "autonomous": True, "approval_required": False, "outreach_state": lead.get("outreach_state"), "next_follow_up_at": lead.get("next_follow_up_at"), "stop_reason": lead.get("outreach_stop_reason"), "action": "superseded", "outcome_recorded": False}
    if str(lead.get("outreach_state") or "").strip().lower() in {"declined", "opted_out", "irrelevant", "converted", "exhausted"}:
        stored = _persist_lead(ctx.db, lead)
        return {"role": "follow_up", "lead": stored, "autonomous": True, "approval_required": False, "outreach_state": stored.get("outreach_state"), "next_follow_up_at": stored.get("next_follow_up_at"), "stop_reason": stored.get("outreach_stop_reason"), "action": "stop", "outcome_recorded": False}
    if not lead.get("outreach_history"):
        raise AgentContractError("follow_up requires an existing outreach history")
    if not outcome:
        raise AgentContractError("follow_up requires an observed outreach outcome")
    updated = apply_outcome(lead, outcome)
    objection = str(payload.get("objection") or "").strip()
    if objection and outcome not in {"opted_out", "declined", "irrelevant", "converted", "exhausted"}:
        updated["outreach_objection"] = objection
    stop_states = {"declined", "opted_out", "irrelevant", "exhausted", "converted"}
    if updated.get("outreach_state") in stop_states:
        stored = _persist_lead(ctx.db, updated)
        return {"role": "follow_up", "lead": stored, "autonomous": True, "approval_required": False, "outreach_state": stored.get("outreach_state"), "next_follow_up_at": stored.get("next_follow_up_at"), "stop_reason": stored.get("outreach_stop_reason"), "action": "stop", "outcome_recorded": True}
    execute = bool(payload.get("execute"))
    if not execute:
        result: Dict[str, Any] = {"role": "follow_up", "lead": dict(lead), "autonomous": True, "approval_required": False, "outreach_state": lead.get("outreach_state"), "next_follow_up_at": lead.get("next_follow_up_at"), "stop_reason": lead.get("outreach_stop_reason"), "action": "prepare_follow_up", "outcome_recorded": True}
        if objection:
            result["objection_response"] = objection_response(objection, str(lead.get("outreach_route") or "the selected service"))
        return result
    research = updated.get("company_research")
    if not isinstance(research, Mapping):
        raise AgentContractError("follow_up requires company research")
    contact_name = str(research.get("decision_maker") or updated.get("contact_name") or "").strip()
    contact_email = str(research.get("decision_maker_email") or research.get("contact_email") or updated.get("contact_email") or "").strip()
    if not contact_name or not contact_email:
        raise AgentContractError("follow_up requires verified contact details")
    route = str(updated.get("outreach_route") or "").strip()
    if not route:
        raise AgentContractError("follow_up requires an active revenue route")
    signal = str(updated.get("current_need") or updated.get("business_need") or updated.get("signal") or updated.get("evidence") or "the need you described").strip()
    if objection:
        body = objection_response(objection, route)
        subject = f"Re: {signal[:72]}" if signal else f"Re: {route}"
    else:
        body = f"Hi {contact_name},\n\nJust following up on my earlier note about {signal.rstrip('.!?')}. If this is still a priority, I can send the most relevant {route} option.\n\nBest,\nThorio"
        subject = str(updated.get("outreach_draft_subject") or f"Re: {signal[:72]}")
    conversation_id = str(updated.get("conversation_id") or f"conversation:{updated['fingerprint']}:{route}")
    transport = ctx.revenue_transport if ctx.revenue_transport is not None else configured_revenue_transport()
    attempt = int(updated.get("outreach_attempt", 0) or 0) + (0 if outcome == "no_response" else 1)
    cadence = build_outreach_decision({**updated, "outreach_state": "ready", "outreach_attempt": attempt})
    action = execute_outbound(ctx.db, worker_capability=PRIVILEGED_CAPABILITY, opportunity_id=str(updated["fingerprint"]), conversation_id=conversation_id, channel=str(updated.get("outreach_channel") or "email"), recipient={"name": contact_name, "email": contact_email}, subject=subject, body=body, transport=transport, idempotency_key=f"followup:{updated['fingerprint']}:{conversation_id}:{attempt}")
    history = list(updated.get("outreach_history") or []) if isinstance(updated.get("outreach_history") or [], list) else []
    history.append({"action_id": action.action_id, "conversation_id": conversation_id, "route": route, "channel": action.channel, "status": action.status, "kind": "follow_up", "provider_result": dict(action.provider_result or {})})
    next_follow_up = cadence.next_follow_up_at
    stored = _persist_lead(ctx.db, {**updated, "conversation_id": conversation_id, "revenue_lifecycle_state": "conversation_active", "outreach_state": "awaiting_response", "outreach_attempt": attempt, "follow_up_due": bool(next_follow_up), "outreach_draft_subject": subject, "outreach_draft_body": body, "outreach_history": history, "last_outreach_action_id": action.action_id, "last_outreach_delivery": dict(action.provider_result or {}), "next_follow_up_at": next_follow_up})
    return {"role": "follow_up", "lead": stored, "autonomous": True, "approval_required": False, "outreach_state": "awaiting_response", "next_follow_up_at": next_follow_up, "action": "send_follow_up", "outcome_recorded": True, "delivery": dict(action.provider_result or {}), "action_id": action.action_id, "conversation_id": conversation_id, "objection_response": objection_reply(objection, route) if objection else None}


def _monitoring(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    from .agent_queue import pending
    tasks = pending(ctx.db)
    return {"role": "monitoring", "queue_depth": len(tasks), "running_count": sum(1 for task in tasks if task.get("status") == "running"), "queued_count": sum(1 for task in tasks if task.get("status") == "queued"), "failed_count": sum(1 for task in tasks if task.get("status") == "failed")}


def _audit(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    qualification = lead.get("qualification_results") or {}
    violations = []
    if lead.get("paxus_true_referral") and not qualification.get("Paxus", {}).get("true_referral"):
        violations.append("paxus_true_referral_without_qualification_evidence")
    if lead.get("qualified") and not lead.get("potential_routes") and not qualification:
        violations.append("global_qualified_without_route_evidence")
    if lead.get("research_status") == "complete":
        research = lead.get("company_research")
        if not isinstance(research, Mapping) or not research.get("decision_maker") or not research.get("decision_maker_evidence"):
            violations.append("research_complete_without_verified_decision_maker")
    return {"role": "audit", "lead": lead, "violations": violations, "passed": not violations}


_DISCOVERY_AGENTS = tuple(_DISCOVERY_SOURCE_ALIASES) + ("web_job_signal",)
_DISCOVERY = {name: _make_discovery_handler(name) for name in _DISCOVERY_AGENTS}
_PROCESSORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "qualification_a": _qualification_a,
    "qualification_b": _qualification_b,
    "company_research": _company_research,
    "paxus_research": _paxus_research,
    "identity_resolution": identity_resolution,
    "duplicate_resolution": _duplicate_resolution,
    "verification": verification,
    "priority": _priority,
    "routing": routing,
    "airtable_integrity": airtable_integrity,
    "outreach_closer": _outreach_closer,
    "follow_up": _follow_up,
    "monitoring": _monitoring,
    "audit": _audit,
}


def handler_registry() -> Dict[str, Callable[..., Dict[str, Any]]]:
    advanced = advanced_handler_registry()
    advanced.pop("outreach_closer", None)
    advanced.pop("follow_up", None)
    return {**_DISCOVERY, **_PROCESSORS, **advanced}


def _validate_specialization(agent: str, handler: Callable[..., Dict[str, Any]]) -> AgentSpecialization:
    specialization = get_specialization(agent)
    if handler is None:
        raise AgentContractError(f"No handler registered for specialist {agent}")
    return specialization


def execute_task(db, task: Mapping[str, Any], *, worker_id: str, heartbeat_before: bool = True) -> AgentExecutionResult:
    task_data = _require_mapping(task, "task")
    agent = str(task_data.get("agent") or "").strip()
    task_id = str(task_data.get("task_id") or "").strip()
    if not agent or not task_id:
        raise AgentContractError("task requires agent and task_id")
    handler = handler_registry().get(agent)
    specialization = _validate_specialization(agent, handler)
    payload = _require_mapping(task_data.get("payload", {}), "payload")
    ctx = AgentExecutionContext(db=db, worker_id=worker_id)
    if heartbeat_before:
        heartbeat(db, task_id, worker_id=worker_id)
    try:
        result = handler(agent, payload, ctx)
        result = _require_mapping(result, "handler result")
        result.setdefault("agent", agent)
        result.setdefault("specialization", specialization.mission)
        result.setdefault("forbidden_actions", list(specialization.forbidden_actions))
        completed = complete(db, task_id, worker_id=worker_id, result=result)
        return AgentExecutionResult(agent=agent, task_id=task_id, status=completed["status"], result=result)
    except RevenueTransportUnavailable as exc:
        queued = retry(db, task_id, worker_id=worker_id, error=str(exc))
        return AgentExecutionResult(agent=agent, task_id=task_id, status=queued["status"], result={"error": str(exc), "retryable": True})
    except Exception as exc:
        failed = fail(db, task_id, worker_id=worker_id, error=str(exc))
        return AgentExecutionResult(agent=agent, task_id=task_id, status=failed["status"], result={"error": str(exc)})


def run_worker_once(db, agent: str, *, worker_id: str, limit: int = 1) -> Dict[str, Any]:
    get_specialization(agent)
    tasks = claim(db, agent, worker_id=worker_id, limit=limit)
    results = [execute_task(db, task, worker_id=worker_id) for task in tasks]
    return {"agent": agent, "worker_id": worker_id, "claimed_count": len(tasks), "completed_count": sum(result.status == "complete" for result in results), "failed_count": sum(result.status == "failed" for result in results), "retryable_count": sum(result.status == "queued" for result in results), "results": [result.result for result in results]}