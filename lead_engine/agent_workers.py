from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping

from .agent_queue import claim, complete, enqueue, fail, heartbeat
from .agent_specializations import AgentSpecialization, get_specialization
from .qualification import apply_company_qualification
from .research_queue import process_paxus_research_queue


class AgentContractError(ValueError):
    """Raised when a worker receives an invalid specialist task or result."""


@dataclass(frozen=True)
class AgentExecutionContext:
    db: Any
    worker_id: str


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
    "x_signal": ("x", "twitter"),
    "threads_signal": ("threads",),
    "reddit_signal": ("reddit",),
    "linkedin_signal": ("linkedin",),
    "facebook_signal": ("facebook",),
    "instagram_signal": ("instagram",),
    "hacker_news_signal": ("hacker news", "hacker_news", "news.ycombinator.com", "hn"),
    "indie_hackers_signal": ("indie hackers", "indie_hackers", "indiehackers"),
    "product_hunt_signal": ("product hunt", "product_hunt", "producthunt"),
}


def _source_text(record: Mapping[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "").strip().lower()
        for key in ("source", "provider", "source_url", "url")
        if str(record.get(key) or "").strip()
    )


def _discovery_handler_for(agent: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    """Run one permanent source specialist without qualification."""
    record = _require_mapping(payload.get("record", payload), "record")
    source = _source_text(record)
    signal = str(record.get("signal") or record.get("evidence") or "").strip()
    if not signal:
        raise AgentContractError(f"{agent} requires observed signal/evidence")

    if agent != "web_job_signal":
        aliases = _DISCOVERY_SOURCE_ALIASES[agent]
        if not any(alias in source for alias in aliases):
            raise AgentContractError(f"{agent} received evidence outside its permanent source lane: {record.get('source')!r}")
    else:
        job_markers = ("job", "jobs", "career", "careers", "hiring", "greenhouse", "lever", "workable", "ashby", "remote", "jobicy", "himalayas", "remote ok", "remotejobs", "arbeitnow", "muse")
        if not any(marker in source for marker in job_markers) and not any(key in record for key in ("job_title", "application_url", "apply_url")):
            raise AgentContractError(f"web_job_signal received evidence that is not identifiable as a job source: {record.get('source')!r}")

    fingerprint = str(record.get("fingerprint") or payload.get("fingerprint") or "").strip()
    lead = ctx.db.get(fingerprint) if fingerprint else None
    provenance = dict(record.get("provenance") or {}) if isinstance(record.get("provenance"), Mapping) else {}
    provenance.update({"collector_agent": agent, "source_lane": agent, "collected_at": datetime.now(timezone.utc).isoformat()})
    normalized = dict(record)
    normalized.update({"source_lane": agent, "observed": True, "qualification_performed": False, "provenance": provenance})

    if fingerprint and lead is not None:
        enqueue(ctx.db, "qualification_a", {"lead": dict(lead), "evidence_events": [normalized], "discovery_agent": agent}, priority=1, dedupe_key=f"qualification_a:{fingerprint}")

    return {"agent": agent, "role": "discovery", "source": record.get("source") or agent, "source_lane": agent, "record": normalized, "observed": True, "qualification_performed": False, "handoff": "qualification_a" if fingerprint and lead is not None else "awaiting_persistence", "provenance": provenance}


def _make_discovery_handler(agent: str) -> Callable[..., Dict[str, Any]]:
    def handler(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
        return _discovery_handler_for(agent, payload, ctx)
    handler.__name__ = f"_{agent}_handler"
    return handler


def _qualification_a(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    evaluated = _persist_lead(ctx.db, apply_company_qualification(lead))
    fingerprint = str(evaluated.get("fingerprint"))
    evidence_events = payload.get("evidence_events", [])
    enqueue(ctx.db, "company_research", {"lead": evaluated, "evidence_events": evidence_events, "research_scope": ("company_identity", "business_context", "current_need", "recent_activity", "decision_maker", "contact_information", "decision_maker_evidence")}, priority=10, dedupe_key=f"company_research:{fingerprint}")
    paxus = (evaluated.get("qualification_results") or {}).get("Paxus", {})
    if paxus.get("qualified") and not paxus.get("true_referral"):
        enqueue(ctx.db, "paxus_research", {"lead": evaluated, "paxus_qualification": paxus}, priority=10, dedupe_key=f"paxus_research:{fingerprint}")
    return {"role": "qualification_a", "lead": evaluated, "qualification_results": evaluated.get("qualification_results", {}), "qualified_companies": evaluated.get("potential_routes", []), "independent_review": "primary", "handoffs": ["company_research"] + (["paxus_research"] if paxus.get("qualified") and not paxus.get("true_referral") else [])}


def _qualification_b(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
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
    verified_fields = tuple(key for key, value in supplied.items() if value not in (None, "", [], {}, ()))
    research_complete = bool(supplied.get("company_verified") and supplied.get("decision_maker") and supplied.get("decision_maker_evidence"))
    status = "complete" if research_complete else "research_required"
    merged = dict(lead)
    if supplied:
        merged["company_research"] = supplied
    merged["research_status"] = status
    merged["research_verified_fields"] = list(verified_fields)
    stored = _persist_lead(ctx.db, merged)
    enqueue(ctx.db, "qualification_b", {"lead": stored, "prior_result": {"agent": "qualification_a", "qualified_companies": stored.get("potential_routes", [])}, "evidence_events": payload.get("evidence_events", []), "research_result": {"status": status, "verified_fields": list(verified_fields)}}, priority=9, dedupe_key=f"qualification_b:{fingerprint}")
    return {"role": "company_research", "lead": stored, "research": supplied, "research_status": status, "verified_fields": list(verified_fields), "decision_maker_verified": bool(supplied.get("decision_maker") and supplied.get("decision_maker_evidence")), "fabricated_fields": [], "handoff": "qualification_b"}


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


def _outreach_closer(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    if payload.get("authorized") is not True:
        raise AgentContractError("outreach_closer requires explicit authorized=True")
    if str(lead.get("research_status") or "").strip().lower() != "complete":
        raise AgentContractError("outreach_closer requires completed company research")
    research = lead.get("company_research")
    if not isinstance(research, Mapping) or not research.get("decision_maker") or not research.get("decision_maker_evidence"):
        raise AgentContractError("outreach_closer requires verified decision-maker research")
    return {"role": "outreach_closer", "lead": lead, "authorized": True, "action": "prepare_authorized_outreach"}


def _follow_up(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    if payload.get("authorized") is not True:
        raise AgentContractError("follow_up requires explicit authorized=True")
    if not lead.get("outreach_history"):
        raise AgentContractError("follow_up requires an existing outreach history")
    return {"role": "follow_up", "lead": lead, "authorized": True, "action": "advance_follow_up_state"}


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


_DISCOVERY_AGENTS = ("x_signal", "threads_signal", "reddit_signal", "linkedin_signal", "facebook_signal", "instagram_signal", "hacker_news_signal", "indie_hackers_signal", "product_hunt_signal", "web_job_signal")
_DISCOVERY = {name: _make_discovery_handler(name) for name in _DISCOVERY_AGENTS}
_PROCESSORS: Dict[str, Callable[..., Dict[str, Any]]] = {"qualification_a": _qualification_a, "qualification_b": _qualification_b, "company_research": _company_research, "paxus_research": _paxus_research, "duplicate_resolution": _duplicate_resolution, "priority": _priority, "outreach_closer": _outreach_closer, "follow_up": _follow_up, "monitoring": _monitoring, "audit": _audit}


def handler_registry() -> Dict[str, Callable[..., Dict[str, Any]]]:
    return {**_DISCOVERY, **_PROCESSORS}


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
    except Exception as exc:
        failed = fail(db, task_id, worker_id=worker_id, error=str(exc))
        return AgentExecutionResult(agent=agent, task_id=task_id, status=failed["status"], result={"error": str(exc)})


def run_worker_once(db, agent: str, *, worker_id: str, limit: int = 1) -> Dict[str, Any]:
    """Claim and execute only this specialist's tasks."""
    get_specialization(agent)
    tasks = claim(db, agent, worker_id=worker_id, limit=limit)
    results = [execute_task(db, task, worker_id=worker_id) for task in tasks]
    return {"agent": agent, "worker_id": worker_id, "claimed_count": len(tasks), "completed_count": sum(result.status == "complete" for result in results), "failed_count": sum(result.status == "failed" for result in results), "results": [result.result for result in results]}
