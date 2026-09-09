"""Bridge durable local specialist work into the authenticated free coordinator.

Only stateless discovery and social-research specialists are eligible for remote
execution. Stateful processing remains local because it requires LeadDB and the
engine's transactional side effects. Completed remote findings are persisted
before the local task is marked complete, so a bridge interruption cannot turn a
successful remote computation into an invisible local loss.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from .advanced_agent_logic import advanced_handler_registry
from .agent_queue import COMPLETE, QUEUED, RUNNING, claim_task, complete, pending, retry
from .compute_worker import ComputeWorkerClient, ComputeWorkerError

REMOTE_SAFE_AGENTS = frozenset(advanced_handler_registry())
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

    from .agent_queue import enqueue
    enqueue(
        db,
        "qualification_a",
        {"lead": stored, "evidence_events": stored.get("specialist_evidence_events", []), "specialist_agent": agent},
        priority=2,
        dedupe_key=f"qualification_a:{fingerprint}",
    )


def publish_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 20) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    candidates = [task for task in pending(db) if task.get("status") == QUEUED and task.get("agent") in REMOTE_SAFE_AGENTS]
    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("created_at", "")))
    published = []
    for task in candidates[:limit]:
        payload = {"kind": "agent_task", "agent": task["agent"], "payload": task["payload"]}
        client.enqueue(payload, task_id=task["task_id"])
        claimed = claim_task(db, task["task_id"], worker_id=f"{REMOTE_WORKER_PREFIX}{client.worker_id}", lease_seconds=900)
        published.append({"task_id": claimed["task_id"], "agent": claimed["agent"]})
    return {"published_count": len(published), "published": published}


def reconcile_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 50) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    local_tasks = [
        task for task in pending(db)
        if task.get("status") == RUNNING and str(task.get("worker_id") or "").startswith(REMOTE_WORKER_PREFIX)
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
            _persist_remote_result(db, agent, result.get("result", result) if isinstance(result.get("result"), Mapping) else result)
            complete(db, task["task_id"], worker_id=task["worker_id"], result=dict(result))
            completed.append(task["task_id"])
        elif status == "queued":
            error = str(remote.get("error") or "remote task returned to queue")
            retry(db, task["task_id"], worker_id=task["worker_id"], error=error)
            retried.append(task["task_id"])
        elif status == "leased":
            continue
        else:
            raise ComputeWorkerError(f"unexpected remote task state {status!r} for {task['task_id']}")
    return {"completed_count": len(completed), "retried_count": len(retried), "completed": completed, "retried": retried}


def bridge_once(db: Any, client: ComputeWorkerClient, *, publish_limit: int = 20, reconcile_limit: int = 50) -> Dict[str, Any]:
    reconciled = reconcile_remote_work(db, client, limit=reconcile_limit)
    published = publish_remote_work(db, client, limit=publish_limit)
    return {"reconciled": reconciled, "published": published}
