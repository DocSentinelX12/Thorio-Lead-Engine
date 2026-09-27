from datetime import datetime, timedelta, timezone

import pytest

from .agent_queue import COMPLETE, QUEUED, RUNNING, claim, complete, enqueue, pending
from .database import LeadDB
from .source_runner import SourceRunner


def _db(tmp_path):
    return LeadDB(data_dir=tmp_path)


def _lead(fingerprint="queue-integrity-lead"):
    return {
        "fingerprint": fingerprint,
        "company": "Queue Integrity Test Co",
        "signal": "Observed hiring need",
    }


def test_batch_write_rolls_back_lead_when_queue_admission_fails(tmp_path, monkeypatch):
    db = _db(tmp_path)

    def fail_queue_insert(rows):
        raise RuntimeError("queue persistence failed")

    monkeypatch.setattr(db, "queue_insert_many", fail_queue_insert)

    with pytest.raises(RuntimeError, match="queue persistence failed"):
        with db.batch_writes():
            assert db.insert_if_new(_lead()) is True
            enqueue(db, "x_signal", {"fingerprint": "queue-integrity-lead"})

    assert db.get("queue-integrity-lead") is None
    assert pending(db) == []


def test_expired_lease_is_recovered_before_capacity_is_calculated(tmp_path):
    db = _db(tmp_path)
    first = enqueue(db, "paxus_research", {"id": "first"}, priority=1)
    claimed = claim(db, "paxus_research", worker_id="worker-a", limit=1, lease_seconds=300)
    assert claimed[0]["task_id"] == first["task_id"]

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert db.queue_update(
        first["task_id"],
        expected_status=RUNNING,
        expected_worker_id="worker-a",
        lease_until=expired,
    ) == 1

    second = enqueue(db, "paxus_research", {"id": "second"}, priority=10)
    reclaimed = claim(db, "paxus_research", worker_id="worker-b", limit=1, lease_seconds=300)

    assert len(reclaimed) == 1
    assert reclaimed[0]["task_id"] == second["task_id"]
    stale = [task for task in pending(db, "paxus_research") if task["task_id"] == first["task_id"]]
    assert stale and stale[0]["status"] == QUEUED and stale[0]["worker_id"] is None


def test_stale_worker_cannot_complete_after_lease_reassignment(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"id": "ownership"})
    claimed = claim(db, "paxus_research", worker_id="worker-a", limit=1, lease_seconds=300)
    assert claimed[0]["task_id"] == task["task_id"]

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert db.queue_update(
        task["task_id"],
        expected_status=RUNNING,
        expected_worker_id="worker-a",
        lease_until=expired,
    ) == 1
    reassigned = claim(db, "paxus_research", worker_id="worker-b", limit=1, lease_seconds=300)
    assert reassigned[0]["worker_id"] == "worker-b"

    with pytest.raises(ValueError, match="Task is not leased to this worker"):
        complete(db, task["task_id"], worker_id="worker-a", result={"status": "stale"})

    finished = complete(db, task["task_id"], worker_id="worker-b", result={"status": "ok"})
    assert finished["status"] == COMPLETE
    assert finished["worker_id"] is None


def test_source_runner_rolls_back_accepted_lead_when_discovery_queue_fails(tmp_path, monkeypatch):
    db = _db(tmp_path)
    fingerprint = "source-runner-atomic-lead"
    lead = _lead(fingerprint)

    class FakePipeline:
        def __init__(self, database):
            self.db = database

        def process(self, **normalized_record):
            assert self.db.insert_if_new(lead) is True
            return {"accepted": True, "fingerprint": fingerprint, "lead": lead, "priority": "high"}

    monkeypatch.setattr("lead_engine.source_runner.normalize_lead_input", lambda record: dict(record))

    def fail_queue_insert(rows):
        raise RuntimeError("discovery queue persistence failed")

    monkeypatch.setattr(db, "queue_insert_many", fail_queue_insert)

    with pytest.raises(RuntimeError, match="discovery queue persistence failed"):
        SourceRunner(FakePipeline(db)).process([{"fingerprint": fingerprint, "company": lead["company"], "signal": lead["signal"], "source": "x"}])

    assert db.get(fingerprint) is None
    assert pending(db) == []


def test_routing_state_and_airtable_task_roll_back_together(tmp_path, monkeypatch):
    from . import active_processing

    db = _db(tmp_path)
    lead = _lead("routing-atomicity")
    lead["qualified"] = True
    assert db.insert_if_new(lead) is True
    monkeypatch.setattr(active_processing, "_routing", lambda agent, payload, ctx: {"destinations": ["Thorio"], "review_required": False})

    def fail_queue_insert(rows):
        raise RuntimeError("airtable queue persistence failed")

    monkeypatch.setattr(db, "queue_insert_many", fail_queue_insert)

    with pytest.raises(RuntimeError, match="airtable queue persistence failed"):
        active_processing.routing(
            "routing",
            {"lead": lead},
            type("Ctx", (), {"db": db})(),
        )

    stored = db.get(lead["fingerprint"])
    assert stored["routing_result"] is None if "routing_result" in stored else True
    assert stored.get("sales_eligibility") is None
    assert pending(db) == []


def test_sales_eligibility_and_closer_task_roll_back_together(tmp_path, monkeypatch):
    from . import active_processing

    db = _db(tmp_path)
    lead = _lead("sales-handoff-atomicity")
    lead.update({
        "qualified": True,
        "business_need": "Remote engineering hiring",
        "business_need_research": {"verified": True, "business_need": "Remote engineering hiring"},
        "company_research": {
            "company_verified": True,
            "decision_maker": "Jane Doe",
            "decision_maker_evidence": "Verified company leadership page",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "jane@example.com",
        },
    })
    assert db.insert_if_new(lead) is True
    monkeypatch.setattr(active_processing, "_airtable_integrity", lambda agent, payload, ctx: {"integrity": "verified"})
    monkeypatch.setattr(active_processing, "_sales_eligibility", lambda lead, routing_result, integrity_result, db: (True, "eligible"))
    monkeypatch.setattr(active_processing, "package_is_ready", lambda lead: True)

    def fail_queue_insert(rows):
        raise RuntimeError("closer queue persistence failed")

    monkeypatch.setattr(db, "queue_insert_many", fail_queue_insert)

    with pytest.raises(RuntimeError, match="closer queue persistence failed"):
        active_processing.airtable_integrity(
            "airtable_integrity",
            {"lead": lead, "routing_result": {"destinations": ["Thorio"], "review_required": False}},
            type("Ctx", (), {"db": db})(),
        )

    stored = db.get(lead["fingerprint"])
    assert stored.get("sales_eligibility") is None
    assert stored.get("revenue_lifecycle_state") is None
    assert pending(db) == []


def test_remote_result_next_task_and_completion_roll_back_together(tmp_path, monkeypatch):
    from .compute_bridge import reconcile_remote_work

    db = _db(tmp_path)
    lead = _lead("remote-handoff-atomicity")
    assert db.insert_if_new(lead) is True
    task = enqueue(db, "engineering_demand_discovery", {"lead": lead})
    claimed = claim(db, "engineering_demand_discovery", worker_id="remote-compute:worker-1", limit=1, lease_seconds=300)
    assert claimed[0]["task_id"] == task["task_id"]

    class FakeRemote:
        def status(self, task_id):
            return {
                "status": "completed",
                "payload": {"agent": "engineering_demand_discovery"},
                "result": {
                    "result": {
                        "fingerprint": lead["fingerprint"],
                        "findings": [{"source": "verified-source", "evidence": "Observed research result"}],
                    }
                },
            }

    def fail_queue_insert(rows):
        raise RuntimeError("next research queue persistence failed")

    monkeypatch.setattr(db, "queue_insert_many", fail_queue_insert)

    with pytest.raises(RuntimeError, match="next research queue persistence failed"):
        reconcile_remote_work(db, FakeRemote(), limit=1)

    stored = db.get(lead["fingerprint"])
    assert "specialist_findings" not in stored
    rows = pending(db, "engineering_demand_discovery")
    assert len(rows) == 1
    assert rows[0]["status"] == RUNNING
    assert rows[0]["worker_id"] == "remote-compute:worker-1"


def test_completed_work_cannot_be_claimed_or_completed_again(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"id": "terminal"})
    claimed = claim(db, "paxus_research", worker_id="worker-terminal", limit=1, lease_seconds=300)
    assert claimed[0]["task_id"] == task["task_id"]
    complete(db, task["task_id"], worker_id="worker-terminal", result={"ok": True})

    assert claim(db, "paxus_research", worker_id="worker-terminal", limit=1, lease_seconds=300) == []
    with pytest.raises(ValueError, match="Task is not leased to this worker"):
        complete(db, task["task_id"], worker_id="worker-terminal", result={"ok": False})

    row = db.queue_get(task["task_id"])
    assert row is not None
    assert row[3] == COMPLETE
    assert pending(db, "paxus_research") == []


def test_failed_work_remains_inspectable_and_is_not_silently_dropped(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"id": "failed"})
    claimed = claim(db, "paxus_research", worker_id="worker-failed", limit=1, lease_seconds=300)
    fail_result = __import__("lead_engine.agent_queue", fromlist=["fail"]).fail(
        db,
        task["task_id"],
        worker_id="worker-failed",
        error="provider failure",
    )
    assert fail_result["status"] == "failed"
    assert pending(db, "paxus_research") == []

    row = db.queue_get(task["task_id"])
    assert row is not None
    assert row[3] == "failed"
    assert row[12] == "provider failure"


def test_retry_preserves_task_identity_and_records_attempts(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"id": "retry"})
    first = claim(db, "paxus_research", worker_id="worker-retry", limit=1, lease_seconds=300)[0]
    assert first["attempts"] == 1
    from .agent_queue import retry
    retried = retry(db, task["task_id"], worker_id="worker-retry", error="temporary provider failure")
    assert retried["task_id"] == task["task_id"]
    assert retried["status"] == QUEUED
    assert retried["last_error"] == "temporary provider failure"

    second = claim(db, "paxus_research", worker_id="worker-retry-2", limit=1, lease_seconds=300)[0]
    assert second["task_id"] == task["task_id"]
    assert second["attempts"] == 2
    assert second["worker_id"] == "worker-retry-2"


def test_queued_work_survives_database_restart(tmp_path):
    db = _db(tmp_path)
    task = enqueue(db, "paxus_research", {"id": "restart"})
    db.close()

    reopened = LeadDB(data_dir=tmp_path)
    try:
        queued = pending(reopened, "paxus_research")
        assert len(queued) == 1
        assert queued[0]["task_id"] == task["task_id"]
        assert queued[0]["status"] == QUEUED
    finally:
        reopened.close()


def test_batch_limit_does_not_discard_durable_backlog(tmp_path):
    db = _db(tmp_path)
    tasks = [
        {"agent": "paxus_research", "payload": {"id": str(index)}, "priority": index}
        for index in range(200)
    ]
    from .agent_queue import enqueue_many
    created = enqueue_many(db, tasks)
    assert len(created) == 200
    assert len(pending(db, "paxus_research")) == 200
