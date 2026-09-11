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
