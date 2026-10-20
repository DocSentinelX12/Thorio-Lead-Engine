"""Bridge durable local specialist work into the authenticated free coordinator."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import math
import sqlite3
import time
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


def _is_sqlite_lock_error(error: BaseException) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "database is locked" in message or "database table is locked" in message


def _read_pending_for_bridge(db: Any, phase: str) -> list[Dict[str, Any]]:
    started = time.monotonic()
    print(f"REMOTE COMPUTE BRIDGE: {phase} queue scan started.", flush=True)
    tasks = pending(db)
    print(
        f"REMOTE COMPUTE BRIDGE: {phase} queue scan finished in "
        f"{time.monotonic() - started:.3f}s with {len(tasks)} active tasks.",
        flush=True,
    )
    return tasks


@contextmanager
def _bounded_sqlite_busy_timeout(db: Any, timeout_ms: int = 250):
    """Keep every SQLite write made during one bridge pass from waiting 120s."""
    connection = getattr(db, "conn", None)
    if connection is None or not hasattr(connection, "execute"):
        yield
        return
    original_timeout = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
    bounded_timeout = min(original_timeout, timeout_ms)
    original_retry_limit = getattr(db, "_write_retry_attempt_limit", None)
    configured_retry_limit = 15 if original_retry_limit is None else int(original_retry_limit)
    try:
        # Bridge work is best-effort and has its own aggregate deadline. Do not
        # let LeadDB's general-purpose 15-attempt contention policy overrun it.
        db._write_retry_attempt_limit = min(configured_retry_limit, 4)
        connection.execute(f"PRAGMA busy_timeout={bounded_timeout}")
        yield
    finally:
        connection.execute(f"PRAGMA busy_timeout={original_timeout}")
        if original_retry_limit is None:
            try:
                delattr(db, "_write_retry_attempt_limit")
            except AttributeError:
                pass
        else:
            db._write_retry_attempt_limit = original_retry_limit


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


def _call_with_deadline(
    client: ComputeWorkerClient,
    method_name: str,
    *args: Any,
    deadline_monotonic: float | None = None,
    **kwargs: Any,
) -> Any:
    remaining = None if deadline_monotonic is None else deadline_monotonic - time.monotonic()
    if remaining is not None and remaining <= 0:
        raise ComputeWorkerError(f"remote compute bridge deadline exceeded before coordinator {method_name}")
    method = getattr(client, method_name)
    if isinstance(client, ComputeWorkerClient) and remaining is not None:
        kwargs["timeout_seconds"] = min(float(client.timeout_seconds), remaining)
    return method(*args, **kwargs)


def publish_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 20, deadline_monotonic: float | None = None) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    worker_id = f"{REMOTE_WORKER_PREFIX}{client.worker_id}"
    optimized_queries = callable(getattr(db, "queue_remote_candidates", None)) and callable(
        getattr(db, "compute_bridge_publications_for_running", None)
    )
    if optimized_queries:
        scan_started = time.monotonic()
        print("REMOTE COMPUTE BRIDGE: bounded publication queue scan started.", flush=True)
        try:
            candidates = db.queue_remote_candidates(REMOTE_SAFE_AGENTS, limit)
            existing_publications = db.compute_bridge_publications_for_running(REMOTE_WORKER_PREFIX, limit)
        except sqlite3.OperationalError as error:
            if not _is_sqlite_lock_error(error):
                raise
            return {
                "status": "degraded",
                "published_count": 0,
                "prepared_count": 0,
                "attempted_count": 0,
                "errors": [{"task_id": None, "error": f"SQLite lock while scanning publication work: {error}"}],
                "published": [],
            }
        print(
            f"REMOTE COMPUTE BRIDGE: bounded publication queue scan finished in "
            f"{time.monotonic() - scan_started:.3f}s; candidates={len(candidates)} "
            f"existing_publications={len(existing_publications)}.",
            flush=True,
        )
    else:
        current_pending = {
            str(task.get("task_id")): task
            for task in _read_pending_for_bridge(db, "publication")
            if isinstance(task, Mapping) and task.get("task_id")
        }
        existing_publications = []
        try:
            for publication in db.compute_bridge_publications():
                task = current_pending.get(str(publication.get("task_id") or ""))
                if (
                    task is not None
                    and task.get("status") == RUNNING
                    and task.get("worker_id") == publication.get("worker_id")
                ):
                    existing_publications.append(publication)
        except sqlite3.OperationalError as error:
            if not _is_sqlite_lock_error(error):
                raise
            return {
                "status": "degraded",
                "published_count": 0,
                "prepared_count": 0,
                "attempted_count": 0,
                "errors": [{"task_id": None, "error": f"SQLite lock while reading publication records: {error}"}],
                "published": [],
            }
        candidates = [
            task for task in current_pending.values()
            if task.get("status") == QUEUED and task.get("agent") in REMOTE_SAFE_AGENTS
        ]

    prepared = 0
    attempted = 0
    published = []
    errors = []

    def publish_one(task_id: str, task_worker_id: str, payload: Mapping[str, Any]) -> bool:
        nonlocal attempted
        attempted += 1
        try:
            _call_with_deadline(client, "enqueue", payload, task_id=task_id, deadline_monotonic=deadline_monotonic)
        except Exception as error:
            try:
                db.compute_bridge_mark_retry(task_id, str(error), _now_iso())
                try:
                    retry(db, task_id, worker_id=task_worker_id, error=str(error))
                except (ValueError, KeyError):
                    # Keep the durable publication error even if a concurrent local
                    # worker already changed the task lease/state.
                    pass
            except sqlite3.OperationalError as db_error:
                if not _is_sqlite_lock_error(db_error):
                    raise
                errors.append({
                    "task_id": task_id,
                    "error": f"SQLite lock while recording coordinator enqueue failure ({error}): {db_error}",
                })
                return False
            errors.append({"task_id": task_id, "error": str(error)})
            return False
        try:
            db.compute_bridge_mark_published(task_id, _now_iso())
        except sqlite3.OperationalError as error:
            if not _is_sqlite_lock_error(error):
                raise
            errors.append({
                "task_id": task_id,
                "error": f"Coordinator accepted task but local SQLite publication update was blocked: {error}",
            })
            return False
        published.append({"task_id": task_id, "agent": str(payload.get("agent") or "")})
        return True

    existing_publications.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("task_id") or "")))
    for publication in existing_publications[:limit]:
        task_id = str(publication["task_id"])
        if not publish_one(task_id, str(publication["worker_id"]), publication["payload"]):
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

    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("created_at", "")))
    for task in candidates:
        if attempted >= limit:
            break
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            errors.append({"task_id": None, "error": "remote compute bridge deadline exceeded before preparing additional work"})
            break
        task_id = str(task["task_id"])
        payload = {
            "kind": "agent_task",
            "agent": task["agent"],
            "payload": task["payload"],
            "compute_requirements": {"workload_class": "cpu_bound", "min_cpu_count": 1, "min_memory_bytes": 1},
        }
        try:
            db.compute_bridge_prepare(task_id, worker_id, payload, _now_iso())
            claim_task(db, task_id, worker_id=worker_id, lease_seconds=900)
        except ValueError:
            continue
        except sqlite3.OperationalError as error:
            if not _is_sqlite_lock_error(error):
                raise
            errors.append({"task_id": task_id, "error": f"SQLite lock while preparing remote work: {error}"})
            break
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

def reconcile_remote_work(db: Any, client: ComputeWorkerClient, *, limit: int = 50, deadline_monotonic: float | None = None) -> Dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    completed = []
    retried = []
    errors = []
    attempted = 0
    try:
        scan_started = time.monotonic()
        print("REMOTE COMPUTE BRIDGE: reconciliation queue scan started.", flush=True)
        if callable(getattr(db, "queue_remote_reconciliation_tasks", None)):
            local_tasks = db.queue_remote_reconciliation_tasks(REMOTE_WORKER_PREFIX, limit)
        else:
            local_tasks = []
            for task in _read_pending_for_bridge(db, "reconciliation"):
                if (
                    task.get("status") != RUNNING
                    or not str(task.get("worker_id") or "").startswith(REMOTE_WORKER_PREFIX)
                ):
                    continue
                bridge_record = db.compute_bridge_get(task["task_id"])
                if bridge_record is None or bridge_record.get("status") == "published":
                    local_tasks.append(task)
        print(
            f"REMOTE COMPUTE BRIDGE: reconciliation queue scan finished in "
            f"{time.monotonic() - scan_started:.3f}s with {len(local_tasks)} eligible remote tasks.",
            flush=True,
        )
    except sqlite3.OperationalError as error:
        if not _is_sqlite_lock_error(error):
            raise
        return {
            "completed_count": 0,
            "retried_count": 0,
            "attempted_count": 0,
            "errors": [{"task_id": None, "error": f"SQLite lock while scanning remote work: {error}"}],
            "completed": [],
            "retried": [],
        }

    for task in local_tasks[:limit]:
        attempted += 1
        try:
            remote = _call_with_deadline(client, "status", task["task_id"], deadline_monotonic=deadline_monotonic)
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
            try:
                # Local persistence and queue completion are one durable
                # transaction. Do not downgrade a local integrity failure into
                # a remote transport warning; let it fail loudly so rollback is tested.
                _persist_remote_result(db, agent, inner)
                complete(db, task["task_id"], worker_id=task["worker_id"], result=dict(result))
            except sqlite3.OperationalError as error:
                if not _is_sqlite_lock_error(error):
                    raise
                errors.append({"task_id": task["task_id"], "error": f"SQLite lock while persisting remote result: {error}"})
                break
            completed.append(task["task_id"])
        elif status == "queued":
            remote_payload = remote.get("payload") if isinstance(remote.get("payload"), Mapping) else {}
            remote_error = str(remote.get("error") or "").strip()
            remote_agent = str(remote_payload.get("agent") or task.get("agent") or "unknown").strip()
            remote_worker = str(remote.get("worker_id") or "").strip() or "unreported"
            remote_attempts = remote.get("attempts", "unreported")
            print(
                "REMOTE COMPUTE BRIDGE: remote task returned to queue "
                f"task_id={task['task_id']} agent={remote_agent} worker={remote_worker} "
                f"attempts={remote_attempts} error={(remote_error or 'none reported')[:1200]}",
                flush=True,
            )
            # A newly published task is normally still queued until the separate
            # GitHub worker workflow starts. Do not revoke the durable local lease
            # just because the first status poll races ahead of worker startup.
            # Genuine worker failures carry an error or a nonzero attempt count
            # and continue through the existing retry/release path below.
            if not remote_error and remote_worker == "unreported" and str(remote_attempts).strip() == "0":
                print(
                    "REMOTE COMPUTE BRIDGE: task has not been claimed by a worker yet; "
                    f"retaining published lease task_id={task['task_id']}.",
                    flush=True,
                )
                continue
            try:
                retry(db, task["task_id"], worker_id=task["worker_id"], error=remote_error or "remote task returned to queue")
            except sqlite3.OperationalError as error:
                if not _is_sqlite_lock_error(error):
                    raise
                errors.append({"task_id": task["task_id"], "error": f"SQLite lock while releasing remote task lease: {error}"})
                break
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

def bridge_once(
    db: Any,
    client: ComputeWorkerClient,
    *,
    publish_limit: int = 20,
    reconcile_limit: int = 50,
    include_lead_compute: bool = False,
    budget_seconds: float = 45.0,
) -> Dict[str, Any]:
    with _bounded_sqlite_busy_timeout(db):
        return _bridge_once(
            db,
            client,
            publish_limit=publish_limit,
            reconcile_limit=reconcile_limit,
            include_lead_compute=include_lead_compute,
            budget_seconds=budget_seconds,
        )


def _bridge_once(
    db: Any,
    client: ComputeWorkerClient,
    *,
    publish_limit: int = 20,
    reconcile_limit: int = 50,
    include_lead_compute: bool = False,
    budget_seconds: float = 45.0,
) -> Dict[str, Any]:
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be a finite positive number")
    started_at = time.monotonic()
    deadline_monotonic = started_at + budget_seconds
    reconcile_started = time.monotonic()
    print("REMOTE COMPUTE BRIDGE: reconciliation started.", flush=True)
    reconciled = reconcile_remote_work(
        db, client, limit=reconcile_limit, deadline_monotonic=deadline_monotonic
    )
    print(
        f"REMOTE COMPUTE BRIDGE: reconciliation finished in "
        f"{time.monotonic() - reconcile_started:.3f}s; completed={reconciled['completed_count']} "
        f"retried={reconciled['retried_count']} errors={len(reconciled['errors'])}.",
        flush=True,
    )
    if time.monotonic() >= deadline_monotonic and not reconciled["errors"]:
        reconciled["errors"].append({
            "task_id": None,
            "error": "remote compute bridge deadline exceeded during reconciliation",
        })
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
        print("REMOTE COMPUTE BRIDGE: publication started.", flush=True)
        publish_started = time.monotonic()
        try:
            published = publish_remote_work(db, client, limit=publish_limit, deadline_monotonic=deadline_monotonic)
        except sqlite3.OperationalError as error:
            if not _is_sqlite_lock_error(error):
                raise
            published = {
                "status": "degraded",
                "published_count": 0,
                "prepared_count": 0,
                "attempted_count": 0,
                "errors": [{"task_id": None, "error": f"SQLite lock during remote publication: {error}"}],
                "published": [],
            }
        print(
            f"REMOTE COMPUTE BRIDGE: publication finished in "
            f"{time.monotonic() - publish_started:.3f}s; published={published['published_count']} "
            f"errors={len(published.get('errors', []))}.",
            flush=True,
        )
    deadline_exceeded = time.monotonic() >= deadline_monotonic
    degraded = bool(reconciled["errors"] or published.get("errors") or deadline_exceeded)
    result = {
        "status": "degraded" if degraded else "ok",
        "completed_count": reconciled["completed_count"],
        "retried_count": reconciled["retried_count"],
        "published_count": published["published_count"],
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "budget_seconds": budget_seconds,
        "deadline_exceeded": deadline_exceeded,
        "reconciled": reconciled,
        "published": published,
    }
    if include_lead_compute and not degraded:
        result["lead_compute"] = lead_compute_once(db, client, dispatch_limit=publish_limit, reconcile_limit=reconcile_limit)
    return result

