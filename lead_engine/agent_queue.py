from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping
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


def _row_to_task(row) -> Dict[str, Any]:
    if row is None:
        return None
    (
        task_id, agent, queue, status, priority, payload, dedupe_key, created_at,
        updated_at, attempts, lease_until, worker_id, last_error, result,
    ) = row
    return {
        "task_id": task_id,
        "agent": agent,
        "queue": queue,
        "status": status,
        "priority": int(priority),
        "payload": json.loads(payload) if isinstance(payload, str) else dict(payload or {}),
        "dedupe_key": dedupe_key,
        "created_at": created_at,
        "updated_at": updated_at,
        "attempts": int(attempts),
        "lease_until": lease_until,
        "worker_id": worker_id,
        "last_error": last_error,
        "result": json.loads(result) if isinstance(result, str) and result else None,
    }


def _load(db) -> Dict[str, Any]:
    state = db.get_state(STATE_KEY)
    if not isinstance(state, dict):
        return {"items": {}}
    items = state.get("items")
    return {"items": items if isinstance(items, dict) else {}}


def _save(db, state: Dict[str, Any]) -> None:
    db.set_state(STATE_KEY, state)


def _queue_db(db) -> bool:
    return all(hasattr(db, name) for name in ("queue_insert_many", "queue_get", "queue_update", "queue_pending"))


def enqueue_many(db, tasks: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Enqueue a source fanout without rewriting the entire queue document.

    LeadDB persists specialist tasks as individual SQLite rows. The legacy
    JSON-state path remains available for lightweight test doubles and older
    database adapters, but production LeadDB uses the incremental row path.
    """
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")
    if not tasks:
        return []

    registry = agent_registry()
    if _queue_db(db):
        now = _iso(_now())
        created: List[Dict[str, Any]] = []
        rows = []
        for specification in tasks:
            if not isinstance(specification, Mapping):
                raise ValueError("each task specification must be a mapping")
            agent = specification.get("agent")
            payload = specification.get("payload")
            priority = specification.get("priority", 0)
            dedupe_key = specification.get("dedupe_key")
            if agent not in registry:
                raise ValueError(f"Unknown agent role: {agent}")
            if not isinstance(payload, dict):
                raise ValueError("payload must be a dictionary")
            duplicate_row = db.queue_find_duplicate(agent, dedupe_key) if dedupe_key else None
            if duplicate_row is not None:
                created.append(_row_to_task(duplicate_row))
                continue
            task = {
                "task_id": uuid4().hex,
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
            rows.append((
                task["task_id"], task["agent"], task["queue"], task["status"], task["priority"],
                json.dumps(task["payload"], ensure_ascii=False), task["dedupe_key"], task["created_at"],
                task["updated_at"], task["attempts"], task["lease_until"], task["worker_id"],
                task["last_error"], None,
            ))
            created.append(task)
        if rows:
            db.queue_insert_many(rows)
        return created

    state = _load(db)
    existing_items = state["items"]
    now = _iso(_now())
    created = []
    for specification in tasks:
        if not isinstance(specification, Mapping):
            raise ValueError("each task specification must be a mapping")
        agent = specification.get("agent")
        payload = specification.get("payload")
        priority = specification.get("priority", 0)
        dedupe_key = specification.get("dedupe_key")
        if agent not in registry:
            raise ValueError(f"Unknown agent role: {agent}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        if dedupe_key:
            duplicate = next((existing for existing in existing_items.values() if existing.get("agent") == agent and existing.get("dedupe_key") == dedupe_key and existing.get("status") in {QUEUED, RUNNING}), None)
            if duplicate is not None:
                created.append(dict(duplicate))
                continue
        task_id = uuid4().hex
        task = {"task_id": task_id, "agent": agent, "queue": registry[agent].queue, "status": QUEUED, "priority": int(priority), "payload": dict(payload), "dedupe_key": dedupe_key, "created_at": now, "updated_at": now, "attempts": 0, "lease_until": None, "worker_id": None, "last_error": None, "result": None}
        existing_items[task_id] = task
        created.append(dict(task))
    _save(db, state)
    return created


def enqueue(db, agent: str, payload: Dict[str, Any], *, priority: int = 0, dedupe_key: str | None = None) -> Dict[str, Any]:
    return enqueue_many(db, [{"agent": agent, "payload": payload, "priority": priority, "dedupe_key": dedupe_key}])[0]


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
    if not task_id:
        raise ValueError("task_id is required")
    if not worker_id:
        raise ValueError("worker_id is required")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    if _queue_db(db):
        row = db.queue_get(task_id)
        task = _row_to_task(row)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != QUEUED:
            raise ValueError(f"Task is not queued: {task_id}")
        now = _now()
        db.queue_update(task_id, status=RUNNING, worker_id=worker_id, lease_until=_iso(now + timedelta(seconds=lease_seconds)), attempts=task["attempts"] + 1, updated_at=_iso(now))
        return _row_to_task(db.queue_get(task_id))
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
    capacity = min(int(limit), registry[agent].max_concurrency)
    if _queue_db(db):
        db.queue_recover_stale(_iso(_now()))
        now = _now()
        rows = db.queue_claim(agent, worker_id, capacity, capacity, _iso(now + timedelta(seconds=lease_seconds)), _iso(now))
        return [_row_to_task(row) for row in rows if row is not None]
    state = _load(db)
    changed = _recover_stale(state)
    active = sum(1 for task in state["items"].values() if task.get("agent") == agent and task.get("status") == RUNNING)
    available = max(0, capacity - active)
    candidates = [task for task in state["items"].values() if task.get("agent") == agent and task.get("status") == QUEUED]
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
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != RUNNING or task.get("worker_id") != worker_id:
            raise ValueError("Task is not leased to this worker")
        now = _now()
        db.queue_update(task_id, lease_until=_iso(now + timedelta(seconds=lease_seconds)), updated_at=_iso(now))
        return _row_to_task(db.queue_get(task_id))
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
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != RUNNING or task.get("worker_id") != worker_id:
            raise ValueError("Task is not leased to this worker")
        now = _iso(_now())
        db.queue_update(task_id, status=QUEUED, last_error=error, worker_id=None, lease_until=None, updated_at=now)
        return _row_to_task(db.queue_get(task_id))
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
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != RUNNING or task.get("worker_id") != worker_id:
            raise ValueError("Task is not leased to this worker")
        db.queue_update(task_id, status=status, result=json.dumps(result, ensure_ascii=False) if result is not None else None, last_error=error, worker_id=None, lease_until=None, updated_at=_iso(_now()))
        return _row_to_task(db.queue_get(task_id))
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
    if _queue_db(db):
        db.queue_recover_stale(_iso(_now()))
        return [_row_to_task(row) for row in db.queue_pending(agent) if row is not None]
    state = _load(db)
    changed = _recover_stale(state)
    if changed:
        _save(db, state)
    tasks = list(state["items"].values())
    if agent is not None:
        tasks = [task for task in tasks if task.get("agent") == agent]
    return [dict(task) for task in tasks if task.get("status") in {QUEUED, RUNNING}]
