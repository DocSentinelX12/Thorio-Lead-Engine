from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import uuid4

from .agent_registry import agent_registry

STATE_KEY = "agent_work_queue"
QUEUED = "queued"
RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _load(db) -> Dict[str, Any]:
    state = db.get_state(STATE_KEY)
    if not isinstance(state, dict):
        return {"items": {}}
    items = state.get("items")
    return {"items": items if isinstance(items, dict) else {}}


def _save(db, state: Dict[str, Any]) -> None:
    db.set_state(STATE_KEY, state)


def enqueue(
    db,
    agent: str,
    payload: Dict[str, Any],
    *,
    priority: int = 0,
    dedupe_key: str | None = None,
) -> Dict[str, Any]:
    registry = agent_registry()
    if agent not in registry:
        raise ValueError(f"Unknown agent role: {agent}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    state = _load(db)
    if dedupe_key:
        for existing in state["items"].values():
            if (
                existing.get("agent") == agent
                and existing.get("dedupe_key") == dedupe_key
                and existing.get("status") in {QUEUED, RUNNING}
            ):
                return dict(existing)

    task_id = uuid4().hex
    now = _iso(_now())
    task = {
        "task_id": task_id,
        "agent": agent,
        "queue": registry[agent].queue,
        "status": QUEUED,
        "priority": int(priority),
        "payload": dict(payload),
        "dedupe_key": dedupe_key,
        "created_at": now,
        "updated_at": now,
        "attempts": 0,
        "lease_until": None,
        "worker_id": None,
        "last_error": None,
        "result": None,
    }
    state["items"][task_id] = task
    _save(db, state)
    return task


def _recover_stale(state: Dict[str, Any]) -> bool:
    now = _now()
    changed = False
    for task in state["items"].values():
        if task.get("status") != RUNNING:
            continue
        lease = task.get("lease_until")
        try:
            lease_dt = datetime.fromisoformat(str(lease)) if lease else None
        except ValueError:
            lease_dt = None
        if lease_dt is not None and lease_dt <= now:
            task["status"] = QUEUED
            task["worker_id"] = None
            task["lease_until"] = None
            task["updated_at"] = _iso(now)
            changed = True
    return changed


def claim_task(db, task_id: str, *, worker_id: str, lease_seconds: int = 300) -> Dict[str, Any]:
    """Atomically claim one exact queued task for a known remote worker."""
    if not task_id:
        raise ValueError("task_id is required")
    if not worker_id:
        raise ValueError("worker_id is required")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    state = _load(db)
    _recover_stale(state)
    task = state["items"].get(task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != QUEUED:
        raise ValueError(f"Task is not queued: {task_id}")
    now = _now()
    task["status"] = RUNNING
    task["worker_id"] = worker_id
    task["lease_until"] = _iso(now + timedelta(seconds=lease_seconds))
    task["attempts"] = int(task.get("attempts", 0)) + 1
    task["updated_at"] = _iso(now)
    _save(db, state)
    return dict(task)


def claim(db, agent: str, *, worker_id: str, limit: int = 1, lease_seconds: int = 300) -> List[Dict[str, Any]]:
    registry = agent_registry()
    if agent not in registry:
        raise ValueError(f"Unknown agent role: {agent}")
    if not worker_id:
        raise ValueError("worker_id is required")
    if limit <= 0 or lease_seconds <= 0:
        raise ValueError("limit and lease_seconds must be positive")

    state = _load(db)
    changed = _recover_stale(state)
    capacity = min(int(limit), registry[agent].max_concurrency)
    active = sum(
        1
        for task in state["items"].values()
        if task.get("agent") == agent and task.get("status") == RUNNING
    )
    available = max(0, capacity - active)

    candidates = [
        task for task in state["items"].values()
        if task.get("agent") == agent and task.get("status") == QUEUED
    ]
    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("created_at", "")))

    claimed = []
    now = _now()
    lease_until = _iso(now + timedelta(seconds=lease_seconds))
    for task in candidates[:available]:
        task["status"] = RUNNING
        task["worker_id"] = worker_id
        task["lease_until"] = lease_until
        task["attempts"] = int(task.get("attempts", 0)) + 1
        task["updated_at"] = _iso(now)
        claimed.append(dict(task))
        changed = True

    if changed:
        _save(db, state)
    return claimed


def heartbeat(db, task_id: str, *, worker_id: str, lease_seconds: int = 300) -> Dict[str, Any]:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    state = _load(db)
    task = state["items"].get(task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != RUNNING or task.get("worker_id") != worker_id:
        raise ValueError("Task is not leased to this worker")
    now = _now()
    task["lease_until"] = _iso(now + timedelta(seconds=lease_seconds))
    task["updated_at"] = _iso(now)
    _save(db, state)
    return dict(task)


def complete(db, task_id: str, *, worker_id: str, result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return _finish(db, task_id, worker_id=worker_id, status=COMPLETE, result=result, error=None)


def fail(db, task_id: str, *, worker_id: str, error: str) -> Dict[str, Any]:
    return _finish(db, task_id, worker_id=worker_id, status=FAILED, result=None, error=error)


def retry(db, task_id: str, *, worker_id: str, error: str) -> Dict[str, Any]:
    """Return a leased task to the queue without losing its failure history."""
    state = _load(db)
    task = state["items"].get(task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != RUNNING or task.get("worker_id") != worker_id:
        raise ValueError("Task is not leased to this worker")
    task["status"] = QUEUED
    task["last_error"] = error
    task["worker_id"] = None
    task["lease_until"] = None
    task["updated_at"] = _iso(_now())
    _save(db, state)
    return dict(task)


def _finish(db, task_id: str, *, worker_id: str, status: str, result: Dict[str, Any] | None, error: str | None) -> Dict[str, Any]:
    state = _load(db)
    task = state["items"].get(task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != RUNNING or task.get("worker_id") != worker_id:
        raise ValueError("Task is not leased to this worker")
    task["status"] = status
    task["result"] = result
    task["last_error"] = error
    task["worker_id"] = None
    task["lease_until"] = None
    task["updated_at"] = _iso(_now())
    _save(db, state)
    return dict(task)


def pending(db, agent: str | None = None) -> List[Dict[str, Any]]:
    state = _load(db)
    changed = _recover_stale(state)
    if changed:
        _save(db, state)
    tasks = list(state["items"].values())
    if agent is not None:
        tasks = [task for task in tasks if task.get("agent") == agent]
    return [dict(task) for task in tasks if task.get("status") in {QUEUED, RUNNING}]
