from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from .agent_queue import COMPLETE, QUEUED, RUNNING, claim, complete, enqueue, enqueue_many, heartbeat, pending
from .agent_registry import agent_registry
from .database import LeadDB


def _db(tmp_path):
    return LeadDB(data_dir=tmp_path)


def test_queue_claim_respects_role_capacity(tmp_path):
    db = _db(tmp_path)
    enqueue(db, "x_signal", {"source": "x"}, priority=1)
    enqueue(db, "x_signal", {"source": "x"}, priority=2)
    enqueue(db, "x_signal", {"source": "x"}, priority=3)

    first = claim(db, "x_signal", worker_id="worker-a", limit=10)
    second = claim(db, "x_signal", worker_id="worker-b", limit=10)

    assert len(first) == 3
    assert len(second) == 0
    assert all(item["status"] == RUNNING for item in first)


def test_queue_lease_heartbeat_and_completion(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"fingerprint": "abc"})

    claimed = claim(db, "paxus_research", worker_id="research-1", limit=1)
    assert claimed[0]["task_id"] == task["task_id"]

    renewed = heartbeat(db, task["task_id"], worker_id="research-1")
    assert renewed["status"] == RUNNING
    assert renewed["lease_until"]

    finished = complete(
        db,
        task["task_id"],
        worker_id="research-1",
        result={"status": "researched"},
    )
    assert finished["status"] == COMPLETE
    assert pending(db, "paxus_research") == []


def test_concurrent_queue_claim_is_atomic_and_unique(tmp_path):
    db = _db(tmp_path)
    tasks = enqueue_many(
        db,
        [
            {"agent": "x_signal", "payload": {"source_id": str(index)}}
            for index in range(20)
        ],
    )
    assert len(tasks) == 20

    role_capacity = agent_registry()["x_signal"].max_concurrency
    barrier = Barrier(20)

    def claim_once(index):
        worker_db = _db(tmp_path)
        try:
            claimed = claim(worker_db, "x_signal", worker_id=f"stress-{index}", limit=1)
            barrier.wait(timeout=10)
            if claimed:
                complete(
                    worker_db,
                    claimed[0]["task_id"],
                    worker_id=f"stress-{index}",
                    result={"status": "stress-complete"},
                )
            return claimed
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(claim_once, range(20)))

    claimed_ids = [item[0]["task_id"] for item in results if item]
    assert len(claimed_ids) == role_capacity
    assert len(set(claimed_ids)) == len(claimed_ids)
    assert len({task["task_id"] for task in tasks} & set(claimed_ids)) == role_capacity
    assert len(pending(db, "x_signal")) == 20 - role_capacity


def test_enqueue_many_uses_incremental_queue_persistence(tmp_path, monkeypatch):
    db = _db(tmp_path)
    calls = []
    original = db.set_state

    def counted_set_state(key, value):
        calls.append(key)
        return original(key, value)

    monkeypatch.setattr(db, "set_state", counted_set_state)
    tasks = enqueue_many(
        db,
        [
            {"agent": "x_signal", "payload": {"source_id": "1"}, "dedupe_key": "x:1"},
            {"agent": "x_signal", "payload": {"source_id": "2"}, "dedupe_key": "x:2"},
            {"agent": "linkedin_signal", "payload": {"source_id": "3"}, "dedupe_key": "li:3"},
        ],
    )

    assert len(tasks) == 3
    assert all(task["status"] == QUEUED for task in tasks)
    assert calls == []
    assert len(pending(db)) == 3
    assert len(db.get_state("agent_work_queue")["items"]) == 3


def test_unknown_agent_is_rejected(tmp_path):
    db = _db(tmp_path)
    try:
        enqueue(db, "not_an_agent", {})
    except ValueError as exc:
        assert "Unknown agent role" in str(exc)
    else:
        raise AssertionError("unknown agent role was accepted")


def test_single_task_claim_reclaims_expired_sqlite_lease(tmp_path, monkeypatch):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"fingerprint": "expired-lease"})
    first = claim(db, "paxus_research", worker_id="worker-old", limit=1, lease_seconds=1)[0]

    expired = "2000-01-01T00:00:00+00:00"
    db.queue_update(first["task_id"], lease_until=expired, updated_at=expired)

    from . import agent_queue
    monkeypatch.setattr(agent_queue, "_now", lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    reclaimed = agent_queue.claim_task(db, task["task_id"], worker_id="worker-new", lease_seconds=300)

    assert reclaimed["task_id"] == task["task_id"]
    assert reclaimed["status"] == RUNNING
    assert reclaimed["worker_id"] == "worker-new"
    assert reclaimed["attempts"] == 2


def test_stale_worker_cannot_complete_after_lease_reclaimed(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"fingerprint": "fence-me"})
    first = claim(db, "paxus_research", worker_id="worker-old", limit=1)
    assert first[0]["task_id"] == task["task_id"]
    old_token = first[0]["lease_token"]
    db.conn.execute(
        "UPDATE agent_queue SET lease_until = ? WHERE task_id = ?",
        ("2000-01-01T00:00:00+00:00", task["task_id"]),
    )
    db.conn.commit()
    recovered = claim(db, "paxus_research", worker_id="worker-new", limit=1)
    assert recovered[0]["worker_id"] == "worker-new"
    try:
        complete(db, task["task_id"], worker_id="worker-old", lease_token=old_token, result={"stale": True})
    except ValueError as exc:
        assert "leased to this worker" in str(exc)
    else:
        raise AssertionError("stale worker was allowed to complete a reclaimed task")


def test_expired_agent_lease_cannot_be_renewed_or_completed(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"fingerprint": "expired-fence"})
    claimed = claim(db, "paxus_research", worker_id="worker-expiring", limit=1)
    token = claimed[0]["lease_token"]
    db.conn.execute(
        "UPDATE agent_queue SET lease_until = ? WHERE task_id = ?",
        ("2000-01-01T00:00:00+00:00", task["task_id"]),
    )
    db.conn.commit()
    try:
        heartbeat(db, task["task_id"], worker_id="worker-expiring", lease_token=token)
    except ValueError as exc:
        assert "lease" in str(exc).lower()
    else:
        raise AssertionError("expired worker lease was renewed")
    try:
        complete(db, task["task_id"], worker_id="worker-expiring", lease_token=token, result={"stale": True})
    except ValueError as exc:
        assert "lease" in str(exc).lower()
    else:
        raise AssertionError("expired worker lease was completed")


def test_queue_claim_retries_transient_sqlite_writer_contention(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "x_signal", {"source_id": "busy-once"})

    import sqlite3

    class BusyOnceConnection:
        def __init__(self, connection):
            self._connection = connection
            self._busy_once = True

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE" and self._busy_once:
                self._busy_once = False
                raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    db.conn = BusyOnceConnection(db.conn)
    claimed = claim(db, "x_signal", worker_id="busy-retry", limit=1)

    assert [item["task_id"] for item in claimed] == [task["task_id"]]
    assert claimed[0]["status"] == RUNNING


def test_concurrent_queue_claim_handles_high_worker_contention(tmp_path):
    db = _db(tmp_path)
    task_count = 64
    tasks = enqueue_many(
        db,
        [
            {"agent": "x_signal", "payload": {"source_id": str(index)}}
            for index in range(task_count)
        ],
    )
    barrier = Barrier(task_count)

    def claim_once(index):
        worker_db = _db(tmp_path)
        worker_id = f"high-contention-{index}"
        try:
            barrier.wait(timeout=20)
            claimed = claim(worker_db, "x_signal", worker_id=worker_id, limit=1)
            if claimed:
                complete(
                    worker_db,
                    claimed[0]["task_id"],
                    worker_id=worker_id,
                    result={"status": "contention-complete"},
                )
            return claimed
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=task_count) as executor:
        results = list(executor.map(claim_once, range(task_count)))

    claimed_ids = [item[0]["task_id"] for item in results if item]
    assert len(claimed_ids) == len(set(claimed_ids))
    assert set(claimed_ids).issubset({task["task_id"] for task in tasks})
