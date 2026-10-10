"""Bridge durable local specialist work into the authenticated free coordinator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .advanced_agent_logic import DISCOVERY_TARGETS, SOCIAL_TARGETS
from .agent_queue import COMPLETE, QUEUED, RUNNING, claim_task, complete, enqueue, pending, retry
from .compute_worker import ComputeWorkerClient, ComputeWorkerError
from .compute_lead_persistence import lead_compute_once

# The remote worker intentionally executes only stateless discovery and social
# evidence analysis. Stateful company research, qualification, routing, and
# revenue roles must remain on the authoritative local LeadDB worker path.
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
    with db.batch_writes():
        stored = db.update_payload(fingerprint, updates)
        if stored is None:
            raise ComputeWorkerError(f"failed to persist remote {agent} result: {fingerprint}")
        if agent in research_agents or agent in discovery_agents:
            enqueue(db, "company_research", {"lead": stored, "evidence_events": stored.get("specialist_evidence_events", []), "specialist_agent": agent}, priority=7, dedupe_key=f"company_research:{fingerprint}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def publish_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 20) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    worker_id = f"{REMOTE_WORKER_PREFIX}{client.worker_id}"
    current_pending = {
        str(task.get("task_id")): task
        for task in pending(db)
        if isinstance(task, Mapping) and task.get("task_id")
    }
    prepared = 0
    attempted = 0
    published = []
    errors = []

    def publish_one(task_id: str, task_worker_id: str, payload: Mapping[str, Any]) -> bool:
        nonlocal attempted
        attempted += 1
        try:
            client.enqueue(payload, task_id=task_id)
        except Exception as error:
            db.compute_bridge_mark_retry(task_id, str(error), _now_iso())
            try:
                retry(db, task_id, worker_id=task_worker_id, error=str(error))
            except (ValueError, KeyError):
                # Keep the durable publication error even if a concurrent local
                # worker already changed the task lease/state.
                pass
            errors.append({"task_id": task_id, "error": str(error)})
            return False
        db.compute_bridge_mark_published(task_id, _now_iso())
        published.append({"task_id": task_id, "agent": str(payload.get("agent") or "")})
        return True

    # Retry existing publication records first. A coordinator failure must not
    # cause the bridge to prepare more remote-owned work or scan the whole queue
    # once per publication.
    existing_publications = []
    for publication in db.compute_bridge_publications():
        task = current_pending.get(str(publication.get("task_id") or ""))
        if (
            task is not None
            and task.get("status") == RUNNING
            and task.get("worker_id") == publication.get("worker_id")
        ):
            existing_publications.append((publication, task))
    for publication, task in existing_publications[:limit]:
        task_id = str(publication["task_id"])
        if not publish_one(task_id, str(task["worker_id"]), publication["payload"]):
            break
    if errors or attempted >= limit:
        return {
            "status": "degraded" if errors else "ok",
            "published_count": len(published),
            "prepared_count": prepared,
            "attempted_count": attempted,
            "errors": errors,
            "published": published,
        }

    candidates = [
        task for task in current_pending.values()
        if task.get("status") == QUEUED and task.get("agent") in REMOTE_SAFE_AGENTS
    ]
    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("created_at", "")))
    for task in candidates:
        if attempted >= limit:
            break
        task_id = str(task["task_id"])
        payload = {
            "kind": "agent_task",
            "agent": task["agent"],
            "payload": task["payload"],
            "compute_requirements": {"workload_class": "cpu_bound", "min_cpu_count": 1, "min_memory_bytes": 1},
        }
        db.compute_bridge_prepare(task_id, worker_id, payload, _now_iso())
        try:
            claim_task(db, task_id, worker_id=worker_id, lease_seconds=900)
        except ValueError:
            continue
        prepared += 1
        if not publish_one(task_id, worker_id, payload):
            break

    return {
        "status": "degraded" if errors else "ok",
        "published_count": len(published),
        "prepared_count": prepared,
        "attempted_count": attempted,
        "errors": errors,
        "published": published,
    }

def reconcile_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 50) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    local_tasks = []
    for task in pending(db):
        if (
            task.get("status") != RUNNING
            or not str(task.get("worker_id") or "").startswith(REMOTE_WORKER_PREFIX)
        ):
            continue
        bridge_record = db.compute_bridge_get(task["task_id"])
        if bridge_record is None or bridge_record.get("status") == "published":
            local_tasks.append(task)

    completed = []
    retried = []
    errors = []
    attempted = 0
    for task in local_tasks[:limit]:
        attempted += 1
        try:
            remote = client.status(task["task_id"])
        except Exception as error:
            errors.append({"task_id": task["task_id"], "error": str(error)})
            break
        status = remote.get("status")
        if status == "completed":
            result = remote.get("result")
            if not isinstance(result, Mapping):
                errors.append({"task_id": task["task_id"], "error": "remote task completed without a result"})
                break
            agent = str(remote.get("payload", {}).get("agent") or task.get("agent") or "")
            inner = result.get("result") if isinstance(result.get("result"), Mapping) else result
            # Local persistence and queue completion are one durable
            # transaction. Do not downgrade a local integrity failure into a
            # remote transport warning; let it fail loudly so rollback is tested.
            _persist_remote_result(db, agent, inner)
            complete(db, task["task_id"], worker_id=task["worker_id"], result=dict(result))
            completed.append(task["task_id"])
        elif status == "queued":
            retry(db, task["task_id"], worker_id=task["worker_id"], error=str(remote.get("error") or "remote task returned to queue"))
            retried.append(task["task_id"])
        elif status == "leased":
            continue
        else:
            errors.append({"task_id": task["task_id"], "error": f"unexpected remote task state {status!r}"})
            break
    return {
        "completed_count": len(completed),
        "retried_count": len(retried),
        "attempted_count": attempted,
        "errors": errors,
        "completed": completed,
        "retried": retried,
    }

def bridge_once(db: Any, client: ComputeWorkerClient, *, publish_limit: int = 20, reconcile_limit: int = 50, include_lead_compute: bool = False) -> Dict[str, Any]:
    reconciled = reconcile_remote_work(db, client, limit=reconcile_limit)
    if reconciled["errors"]:
        published = {
            "status": "skipped",
            "completed_count": 0,
            "retried_count": 0,
            "published_count": 0,
            "prepared_count": 0,
            "attempted_count": 0,
            "errors": [],
            "published": [],
        }
    else:
        published = publish_remote_work(db, client, limit=publish_limit)
    degraded = bool(reconciled["errors"] or published.get("errors"))
    result = {
        "status": "degraded" if degraded else "ok",
        "completed_count": reconciled["completed_count"],
        "retried_count": reconciled["retried_count"],
        "published_count": published["published_count"],
        "reconciled": reconciled,
        "published": published,
    }
    if include_lead_compute and not degraded:
        result["lead_compute"] = lead_compute_once(db, client, dispatch_limit=publish_limit, reconcile_limit=reconcile_limit)
    return result

