from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping

from .agent_queue import claim, complete, fail, heartbeat
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
    lead = payload.get("lead", payload)
    return _require_mapping(lead, "lead")


def _discovery_handler(agent: str, payload: Mapping[str, Any], _: AgentExecutionContext) -> Dict[str, Any]:
    """Normalize evidence supplied by an authorized discovery adapter.

    Discovery workers never invent signals and never perform qualification.
    The collector must supply the observed record; this worker stamps the
    specialist identity so downstream provenance can distinguish collectors.
    """
    record = _require_mapping(payload.get("record", payload), "record")
    source = str(record.get("source") or agent).strip()
    signal = str(record.get("signal") or record.get("evidence") or "").strip()
    if not signal:
        raise AgentContractError("discovery record requires observed signal/evidence")
    return {
        "agent": agent,
        "role": "discovery",
        "source": source,
        "record": record,
        "observed": True,
        "qualification_performed": False,
        "provenance": {
            "collector_agent": agent,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _qualification_a(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    evaluated = apply_company_qualification(lead)
    return {
        "role": "qualification_a",
        "lead": evaluated,
        "qualification_results": evaluated.get("qualification_results", {}),
        "qualified_companies": evaluated.get("potential_routes", []),
        "independent_review": "primary",
    }


def _qualification_b(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    evaluated = apply_company_qualification(lead)
    prior = payload.get("prior_result")
    if prior is not None and not isinstance(prior, Mapping):
        raise AgentContractError("prior_result must be a mapping when supplied")
    return {
        "role": "qualification_b",
        "lead": evaluated,
        "qualification_results": evaluated.get("qualification_results", {}),
        "qualified_companies": evaluated.get("potential_routes", []),
        "independent_review": "validation",
        "challenged_prior_result": prior is not None,
    }


def _company_research(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    evidence = _require_mapping(payload.get("research", {}), "research")
    return {
        "role": "company_research",
        "lead": lead,
        "research": evidence,
        "evidence_only": True,
        "fabricated_fields": [],
    }


def _paxus_research(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    result = process_paxus_research_queue(ctx.db, limit=1)
    return {
        "role": "paxus_research",
        "lead": lead,
        "queue_result": result,
        "true_referral": bool((lead.get("qualification_results") or {}).get("Paxus", {}).get("true_referral")),
    }


def _duplicate_resolution(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes, Mapping)):
        raise AgentContractError("candidates must be a list-like collection")
    candidate_list = [dict(item) for item in candidates if isinstance(item, Mapping)]
    return {
        "role": "duplicate_resolution",
        "lead": lead,
        "candidate_count": len(candidate_list),
        "decision": payload.get("decision", "requires_identity_comparison"),
        "preserve_distinct_opportunities": True,
    }


def _priority(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    evidence = sum(1 for key in ("signal", "evidence", "job_title", "person", "company") if str(lead.get(key) or "").strip())
    qualified = bool(lead.get("qualified") or lead.get("potential_routes"))
    freshness = bool(lead.get("need_at") or lead.get("current_need_at") or lead.get("inquiry_at") or lead.get("last_inquiry_at") or lead.get("intent_at"))
    score = evidence + (5 if qualified else 0) + (3 if freshness else 0)
    return {"role": "priority", "priority_score": score, "lead": lead, "inputs_used": ["evidence", "qualification", "freshness"]}


def _outreach_closer(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    if payload.get("authorized") is not True:
        raise AgentContractError("outreach_closer requires explicit authorized=True")
    return {"role": "outreach_closer", "lead": lead, "authorized": True, "action": "prepare_authorized_outreach"}


def _follow_up(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    if payload.get("authorized") is not True:
        raise AgentContractError("follow_up requires explicit authorized=True")
    return {"role": "follow_up", "lead": lead, "authorized": True, "action": "advance_follow_up_state"}


def _monitoring(_: str, payload: Mapping[str, Any], ctx: AgentExecutionContext) -> Dict[str, Any]:
    from .agent_queue import pending

    tasks = pending(ctx.db)
    return {
        "role": "monitoring",
        "queue_depth": len(tasks),
        "running_count": sum(1 for task in tasks if task.get("status") == "running"),
        "queued_count": sum(1 for task in tasks if task.get("status") == "queued"),
    }


def _audit(_: str, payload: Mapping[str, Any], __: AgentExecutionContext) -> Dict[str, Any]:
    lead = _lead_payload(payload)
    qualification = lead.get("qualification_results") or {}
    violations = []
    if lead.get("paxus_true_referral") and not qualification.get("Paxus", {}).get("true_referral"):
        violations.append("paxus_true_referral_without_qualification_evidence")
    if lead.get("qualified") and not lead.get("potential_routes") and not qualification:
        violations.append("global_qualified_without_route_evidence")
    return {"role": "audit", "lead": lead, "violations": violations, "passed": not violations}


_DISCOVERY = {name: _discovery_handler for name in (
    "x_signal", "threads_signal", "reddit_signal", "linkedin_signal", "facebook_signal",
    "instagram_signal", "hacker_news_signal", "indie_hackers_signal", "product_hunt_signal", "web_job_signal",
)}
_PROCESSORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "qualification_a": _qualification_a,
    "qualification_b": _qualification_b,
    "company_research": _company_research,
    "paxus_research": _paxus_research,
    "duplicate_resolution": _duplicate_resolution,
    "priority": _priority,
    "outreach_closer": _outreach_closer,
    "follow_up": _follow_up,
    "monitoring": _monitoring,
    "audit": _audit,
}


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
    return {
        "agent": agent,
        "worker_id": worker_id,
        "claimed_count": len(tasks),
        "completed_count": sum(result.status == "complete" for result in results),
        "failed_count": sum(result.status == "failed" for result in results),
        "results": [result.result for result in results],
    }
