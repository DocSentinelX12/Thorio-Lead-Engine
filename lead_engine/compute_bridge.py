"""Bridge durable local specialist work into the authenticated free coordinator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .advanced_agent_logic import DISCOVERY_TARGETS, SOCIAL_TARGETS
from .agent_queue import COMPLETE, QUEUED, RUNNING, claim_task, complete, enqueue, pending, retry
from .compute_worker import ComputeWorkerClient, ComputeWorkerError
from .compute_lead_persistence import lead_compute_once

# Only stateless agents whose worker implementation actually executes them may
# cross the remote boundary. Stateful specialists stay on the authoritative
# Thorio execution path until a durable stateful adapter exists.
REMOTE_SAFE_AGENTS = frozenset(set(DISCOVERY_TARGETS) | set(SOCIAL_TARGETS))
REMOTE_WORKER_PREFIX = "remote-compute:"


def _persist_remote_result(db: Any, agent: str, result: Mapping[str, Any]) -> None:
    fingerprint = str(result.get("fingerprint") or "").strip()
    if not fingerprint:
        raise ComputeWorkerError(f"remote {agent} result has no lead fingerprint")
    lead = db.get(fingerprint)
    if lead is None:
        raise ComputeWorkerError(f"remote {agent} result references missing lead: {fingerprint}")
    findings = lead.get("specialist_findings")
    if not isinstance(findings, dict):
        findings = {}
    findings[agent] = dict(result)
    updates: Dict[str, Any] = {"specialist_findings": findings}
    evidence = result.get("findings")
    if isinstance(evidence, list):
        existing_events = lead.get("specialist_evidence_events")
        if not isinstance(existing_events, list):
            existing_events = []
        existing_events = [item for item in existing_events if not (isinstance(item, Mapping) and item.get("agent") == agent)]
        existing_events.extend({"agent": agent, **dict(item)} for item in evidence if isinstance(item, Mapping))
        updates["specialist_evidence_events"] = existing_events
    stored = db.update_payload(fingerprint, updates)
    if stored is None:
        raise ComputeWorkerError(f"failed to persist remote {agent} result: {fingerprint}")
    research_agents = {
        "company_research",
        "social_intelligence",
        "social_hiring_research",
        "social_decision_maker_research",
        "social_inquiry_research",
        "social_company_context",
    }
    discovery_agents = {
        "engineering_demand_discovery",
        "ai_demand_discovery",
        "product_design_demand_discovery",
        "contract_team_demand_discovery",
        "recent_inquiry_discovery",
    }
    if agent in research_agents or agent in discovery_agents:
        enqueue(db, "company_research", {"lead": stored, "evidence_events": stored.get("specialist_evidence_events", []), "specialist_agent": agent}, priority=7, dedupe_key=f"company_research:{fingerprint}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def publish_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 20) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    worker_id = f"{REMOTE_WORKER_PREFIX}{client.worker_id}"
    candidates = [task for task in pending(db) if task.get("status") == QUEUED and task.get("agent") in REMOTE_SAFE_AGENTS]
    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("created_at", "")))
    prepared = 0
    for task in candidates[:limit]:
        payload = {
            "kind": "agent_task",
            "agent": task["agent"],
            "payload": task["payload"],
            "compute_requirements": {"workload_class": "cpu_bound", "min_cpu_count": 1, "min_memory_bytes": 1},
        }
        db.compute_bridge_prepare(task["task_id"], worker_id, payload, _now_iso())
        try:
            claim_task(db, task["task_id"], worker_id=worker_id, lease_seconds=900)
            prepared += 1
        except ValueError:
            continue

    published = []
    for publication in db.compute_bridge_publications():
        if len(published) >= limit:
            break
        task = next((item for item in pending(db) if item.get("task_id") == publication["task_id"]), None)
        if task is None or task.get("status") != RUNNING or task.get("worker_id") != publication["worker_id"]:
            continue
        try:
            client.enqueue(publication["payload"], task_id=publication["task_id"])
            db.compute_bridge_mark_published(publication["task_id"], _now_iso())
            published.append({"task_id": task["task_id"], "agent": task["agent"]})
        except Exception as error:
            db.compute_bridge_mark_retry(publication["task_id"], str(error), _now_iso())
    return {"published_count": len(published), "prepared_count": prepared, "published": published}


def reconcile_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 50) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    local_tasks = [
        task for task in pending(db)
        if task.get("status") == RUNNING
        and str(task.get("worker_id") or "").startswith(REMOTE_WORKER_PREFIX)
        and (db.compute_bridge_get(task["task_id"]) or {}).get("status") == "published"
    ]
    completed = []
    retried = []
    for task in local_tasks[:limit]:
        remote = client.status(task["task_id"])
        status = remote.get("status")
        if status == "completed":
            result = remote.get("result")
            if not isinstance(result, Mapping):
                raise ComputeWorkerError(f"remote task {task['task_id']} completed without a result")
            agent = str(remote.get("payload", {}).get("agent") or task.get("agent") or "")
            inner = result.get("result") if isinstance(result.get("result"), Mapping) else result
            _persist_remote_result(db, agent, inner)
            complete(db, task["task_id"], worker_id=task["worker_id"], result=dict(result))
            completed.append(task["task_id"])
        elif status == "queued":
            retry(db, task["task_id"], worker_id=task["worker_id"], error=str(remote.get("error") or "remote task returned to queue"))
            retried.append(task["task_id"])
        elif status == "leased":
            continue
        else:
            raise ComputeWorkerError(f"unexpected remote task state {status!r} for {task['task_id']}")
    return {"completed_count": len(completed), "retried_count": len(retried), "completed": completed, "retried": retried}


def bridge_once(db: Any, client: ComputeWorkerClient, *, publish_limit: int = 20, reconcile_limit: int = 50, include_lead_compute: bool = False) -> Dict[str, Any]:
    reconciled = reconcile_remote_work(db, client, limit=reconcile_limit)
    published = publish_remote_work(db, client, limit=publish_limit)
    result = {"status": "ok", "completed_count": reconciled["completed_count"], "retried_count": reconciled["retried_count"], "published_count": published["published_count"], "reconciled": reconciled, "published": published}
    if include_lead_compute:
        result["lead_compute"] = lead_compute_once(db, client, dispatch_limit=publish_limit, reconcile_limit=reconcile_limit)
    return result
