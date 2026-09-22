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
CLOSER_ROLE = "high_ticket_sales_closer"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _row_to_task(row) -> Dict[str, Any]:
    if row is None:
        return None
    (task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token) = row
    return {"task_id": task_id, "agent": agent, "queue": queue, "status": status, "priority": int(priority), "payload": json.loads(payload) if isinstance(payload, str) else dict(payload or {}), "dedupe_key": dedupe_key, "created_at": created_at, "updated_at": updated_at, "attempts": int(attempts), "lease_until": lease_until, "worker_id": worker_id, "last_error": last_error, "result": json.loads(result) if isinstance(result, str) and result else None, "lease_token": row[14]}


def _load(db) -> Dict[str, Any]:
    state = db.get_state(STATE_KEY)
    if not isinstance(state, dict): return {"items": {}}
    items = state.get("items")
    return {"items": items if isinstance(items, dict) else {}}


def _save(db, state: Dict[str, Any]) -> None:
    db.set_state(STATE_KEY, state)


def _queue_db(db) -> bool:
    return all(hasattr(db, name) for name in ("queue_insert_many", "queue_get", "queue_update", "queue_pending"))


def _validate_task_authorization(agent: str, payload: Mapping[str, Any]) -> None:
    if agent == "follow_up" and str(payload.get("authorized_by_role") or "").strip().lower() != CLOSER_ROLE:
        raise ValueError("follow_up tasks require authorization by high_ticket_sales_closer")


def _verification_stage(payload: Mapping[str, Any]) -> str:
    """Return the qualification state that a verification task is evaluating.

    Verification is stage-sensitive. A verification task created before final
    qualification must not suppress a later verification task created after an
    independent qualification result becomes available.
    """
    lead = payload.get("lead", payload)
    if not isinstance(lead, Mapping):
        return ""
    return str(lead.get("qualification_review_stage") or "").strip().lower()


def _same_verification_stage(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> bool:
    if existing.get("agent") != "verification":
        return True
    return _verification_stage(existing.get("payload") or {}) == _verification_stage(incoming)


def enqueue_many(db, tasks: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Enqueue specialist tasks with durable per-row persistence."""
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")
    if not tasks: return []
    registry = agent_registry()
    for specification in tasks:
        if not isinstance(specification, Mapping): raise ValueError("each task specification must be a mapping")
        agent = specification.get("agent"); payload = specification.get("payload")
        if agent not in registry: raise ValueError(f"Unknown agent role: {agent}")
        if not isinstance(payload, dict): raise ValueError("payload must be a dictionary")
        _validate_task_authorization(str(agent), payload)

    if _queue_db(db):
        # Duplicate detection and insertion must be one SQLite write transaction.
        # Otherwise two scheduler processes can both observe an empty dedupe key
        # and insert the same logical work before either commit becomes visible.
        now = _iso(_now()); created: List[Dict[str, Any]] = []; rows = []
        db.conn.execute("BEGIN IMMEDIATE")
        try:
            for specification in tasks:
                agent = specification.get("agent"); payload = specification.get("payload"); priority = specification.get("priority", 0); dedupe_key = specification.get("dedupe_key")
                duplicate_row = db.queue_find_duplicate(agent, dedupe_key) if dedupe_key else None
                if duplicate_row is not None:
                    duplicate_task = _row_to_task(duplicate_row)
                    if not (agent == "verification" and not _same_verification_stage(duplicate_task, {"agent": agent, "payload": payload})):
                        created.append(duplicate_task); continue
                task = {"task_id": uuid4().hex, "agent": agent, "queue": registry[agent].queue, "status": QUEUED, "priority": int(priority), "payload": dict(payload), "dedupe_key": dedupe_key, "created_at": now, "updated_at": now, "attempts": 0, "lease_until": None, "worker_id": None, "last_error": None, "result": None}
                rows.append((task["task_id"], task["agent"], task["queue"], task["status"], task["priority"], json.dumps(task["payload"], ensure_ascii=False), task["dedupe_key"], task["created_at"], task["updated_at"], task["attempts"], task["lease_until"], task["worker_id"], task["last_error"], None, None))
                created.append(task)
            if rows:
                db.conn.executemany("INSERT OR IGNORE INTO agent_queue (task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            db.conn.commit()
            return created
        except Exception:
            db.conn.rollback()
            raise

    state = _load(db); existing_items = state["items"]; now = _iso(_now()); created = []
    for specification in tasks:
        agent = specification.get("agent"); payload = specification.get("payload"); priority = specification.get("priority", 0); dedupe_key = specification.get("dedupe_key")
        if dedupe_key:
            duplicate = next((existing for existing in existing_items.values() if existing.get("agent") == agent and existing.get("dedupe_key") == dedupe_key and existing.get("status") in {QUEUED, RUNNING}), None)
            if duplicate is not None:
                if not (agent == "verification" and not _same_verification_stage(duplicate, {"agent": agent, "payload": payload})):
                    created.append(dict(duplicate)); continue
        task_id = uuid4().hex
        task = {"task_id": task_id, "agent": agent, "queue": registry[agent].queue, "status": QUEUED, "priority": int(priority), "payload": dict(payload), "dedupe_key": dedupe_key, "created_at": now, "updated_at": now, "attempts": 0, "lease_until": None, "worker_id": None, "last_error": None, "result": None}
        existing_items[task_id] = task; created.append(dict(task))
    _save(db, state); return created


def enqueue(db, agent: str, payload: Dict[str, Any], *, priority: int = 0, dedupe_key: str | None = None) -> Dict[str, Any]:
    return enqueue_many(db, [{"agent": agent, "payload": payload, "priority": priority, "dedupe_key": dedupe_key}])[0]


def _recover_stale(state: Dict[str, Any]) -> bool:
    now = _now(); changed = False
    for task in state["items"].values():
        if task.get("status") != RUNNING: continue
        lease = task.get("lease_until")
        try: lease_dt = datetime.fromisoformat(str(lease)) if lease else None
        except ValueError: lease_dt = None
        if lease_dt is not None and lease_dt <= now:
            task["status"] = QUEUED; task["worker_id"] = None; task["lease_until"] = None; task["updated_at"] = _iso(now); changed = True
    return changed


def claim_task(db, task_id: str, *, worker_id: str, lease_seconds: int = 300) -> Dict[str, Any]:
    if not task_id: raise ValueError("task_id is required")
    if not worker_id: raise ValueError("worker_id is required")
    if lease_seconds <= 0: raise ValueError("lease_seconds must be positive")
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None: raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != QUEUED: raise ValueError(f"Task is not queued: {task_id}")
        _validate_task_authorization(task["agent"], task.get("payload") or {})
        now = _now(); db.queue_update(task_id, status=RUNNING, worker_id=worker_id, lease_until=_iso(now + timedelta(seconds=lease_seconds)), lease_token=uuid4().hex, attempts=task["attempts"] + 1, updated_at=_iso(now)); return _row_to_task(db.queue_get(task_id))
    state = _load(db); _recover_stale(state); task = state["items"].get(task_id)
    if task is None: raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != QUEUED: raise ValueError(f"Task is not queued: {task_id}")
    _validate_task_authorization(task["agent"], task.get("payload") or {})
    now = _now(); task["status"] = RUNNING; task["worker_id"] = worker_id; task["lease_until"] = _iso(now + timedelta(seconds=lease_seconds)); task["attempts"] = int(task.get("attempts", 0)) + 1; task["updated_at"] = _iso(now); _save(db, state); return dict(task)


def claim(db, agent: str, *, worker_id: str, limit: int = 1, lease_seconds: int = 300) -> List[Dict[str, Any]]:
    registry = agent_registry()
    if agent not in registry: raise ValueError(f"Unknown agent role: {agent}")
    if not worker_id: raise ValueError("worker_id is required")
    if limit <= 0 or lease_seconds <= 0: raise ValueError("limit and lease_seconds must be positive")
    capacity = min(int(limit), registry[agent].max_concurrency)
    if _queue_db(db):
        # Claim first. Queue claiming already uses one IMMEDIATE transaction,
        # so concurrent workers serialize safely instead of all performing a
        # separate stale-lease UPDATE before they contend for the writer lock.
        now = _now()
        tasks = [_row_to_task(row) for row in db.queue_claim(agent, worker_id, capacity, capacity, _iso(now + timedelta(seconds=lease_seconds)), _iso(now)) if row is not None]
        if not tasks:
            # Only touch stale leases when the normal claim found no work.
            # This keeps the hot backlog path read/claim focused while still
            # recovering abandoned work when a queue would otherwise appear empty.
            if db.queue_recover_stale(_iso(_now())):
                now = _now()
                tasks = [_row_to_task(row) for row in db.queue_claim(agent, worker_id, capacity, capacity, _iso(now + timedelta(seconds=lease_seconds)), _iso(now)) if row is not None]
        for task in tasks: _validate_task_authorization(task["agent"], task.get("payload") or {})
        return tasks
    state = _load(db); changed = _recover_stale(state); active = sum(1 for task in state["items"].values() if task.get("agent") == agent and task.get("status") == RUNNING); available = max(0, capacity - active); candidates = [task for task in state["items"].values() if task.get("agent") == agent and task.get("status") == QUEUED]; candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("created_at", ""))); claimed = []; now = _now(); lease_until = _iso(now + timedelta(seconds=lease_seconds))
    for task in candidates[:available]:
        _validate_task_authorization(task["agent"], task.get("payload") or {})
        task["status"] = RUNNING; task["worker_id"] = worker_id; task["lease_until"] = lease_until; task["attempts"] = int(task.get("attempts", 0)) + 1; task["updated_at"] = _iso(now); claimed.append(dict(task)); changed = True
    if changed: _save(db, state)
    return claimed


def heartbeat(db, task_id: str, *, worker_id: str, lease_seconds: int = 300, lease_token: str | None = None) -> Dict[str, Any]:
    if lease_seconds <= 0: raise ValueError("lease_seconds must be positive")
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None: raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != RUNNING or task.get("worker_id") != worker_id or (lease_token is not None and task.get("lease_token") != lease_token): raise ValueError("Task is not leased to this worker")
        now = _now()
        if lease_token is not None and hasattr(db, "queue_update_owned"):
            if not db.queue_update_owned(task_id, worker_id, lease_token, lease_until=_iso(now + timedelta(seconds=lease_seconds)), updated_at=_iso(now)):
                raise ValueError("Task lease was lost")
        else:
            db.queue_update(task_id, lease_until=_iso(now + timedelta(seconds=lease_seconds)), updated_at=_iso(now))
        return _row_to_task(db.queue_get(task_id))
    state = _load(db); task = state["items"].get(task_id)
    if task is None: raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != RUNNING or task.get("worker_id") != worker_id: raise ValueError("Task is not leased to this worker")
    now = _now(); task["lease_until"] = _iso(now + timedelta(seconds=lease_seconds)); task["updated_at"] = _iso(now); _save(db, state); return dict(task)


def complete(db, task_id: str, *, worker_id: str, lease_token: str | None = None, result: Dict[str, Any] | None = None) -> Dict[str, Any]: return _finish(db, task_id, worker_id=worker_id, lease_token=lease_token, status=COMPLETE, result=result, error=None)

def fail(db, task_id: str, *, worker_id: str, lease_token: str | None = None, error: str) -> Dict[str, Any]: return _finish(db, task_id, worker_id=worker_id, lease_token=lease_token, status=FAILED, result=None, error=error)

def retry(db, task_id: str, *, worker_id: str, lease_token: str | None = None, error: str) -> Dict[str, Any]:
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None: raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != RUNNING or task.get("worker_id") != worker_id or (lease_token is not None and task.get("lease_token") != lease_token): raise ValueError("Task is not leased to this worker")
        now = _iso(_now())
        if lease_token is not None and hasattr(db, "queue_update_owned"):
            if not db.queue_update_owned(task_id, worker_id, lease_token, status=QUEUED, last_error=error, worker_id=None, lease_until=None, lease_token=None, updated_at=now):
                raise ValueError("Task lease was lost")
        else:
            db.queue_update(task_id, status=QUEUED, last_error=error, worker_id=None, lease_until=None, updated_at=now)
        return _row_to_task(db.queue_get(task_id))
    state = _load(db); task = state["items"].get(task_id)
    if task is None: raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != RUNNING or task.get("worker_id") != worker_id: raise ValueError("Task is not leased to this worker")
    task["status"] = QUEUED; task["last_error"] = error; task["worker_id"] = None; task["lease_until"] = None; task["updated_at"] = _iso(_now()); _save(db, state); return dict(task)


def _finish(db, task_id: str, *, worker_id: str, lease_token: str | None, status: str, result: Dict[str, Any] | None, error: str | None) -> Dict[str, Any]:
    if _queue_db(db):
        task = _row_to_task(db.queue_get(task_id))
        if task is None: raise ValueError(f"Task not found: {task_id}")
        if task.get("status") != RUNNING or task.get("worker_id") != worker_id or (lease_token is not None and task.get("lease_token") != lease_token): raise ValueError("Task is not leased to this worker")
        now = _iso(_now())
        if lease_token is not None and hasattr(db, "queue_update_owned"):
            if not db.queue_update_owned(task_id, worker_id, lease_token, status=status, result=json.dumps(result, ensure_ascii=False) if result is not None else None, last_error=error, worker_id=None, lease_until=None, lease_token=None, updated_at=now):
                raise ValueError("Task lease was lost")
        else:
            db.queue_update(task_id, status=status, result=json.dumps(result, ensure_ascii=False) if result is not None else None, last_error=error, worker_id=None, lease_until=None, updated_at=now)
        return _row_to_task(db.queue_get(task_id))
    state = _load(db); task = state["items"].get(task_id)
    if task is None: raise ValueError(f"Task not found: {task_id}")
    if task.get("status") != RUNNING or task.get("worker_id") != worker_id: raise ValueError("Task is not leased to this worker")
    task["status"] = status; task["result"] = result; task["last_error"] = error; task["worker_id"] = None; task["lease_until"] = None; task["updated_at"] = _iso(_now()); _save(db, state); return dict(task)


def pending(db, agent: str | None = None) -> List[Dict[str, Any]]:
    if _queue_db(db): db.queue_recover_stale(_iso(_now())); return [_row_to_task(row) for row in db.queue_pending(agent) if row is not None]
    state = _load(db); changed = _recover_stale(state)
    if changed: _save(db, state)
    tasks = list(state["items"].values())
    if agent is not None: tasks = [task for task in tasks if task.get("agent") == agent]
    return [dict(task) for task in tasks if task.get("status") in {QUEUED, RUNNING}]
