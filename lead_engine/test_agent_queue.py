from .agent_queue import COMPLETE, QUEUED, RUNNING, claim, complete, enqueue, heartbeat, pending
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


def test_unknown_agent_is_rejected(tmp_path):
    db = _db(tmp_path)
    try:
        enqueue(db, "not_an_agent", {})
    except ValueError as exc:
        assert "Unknown agent role" in str(exc)
    else:
        raise AssertionError("unknown agent role was accepted")
