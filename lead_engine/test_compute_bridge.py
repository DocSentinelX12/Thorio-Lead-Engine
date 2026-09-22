import tempfile
from pathlib import Path

from .agent_queue import enqueue, pending
from .compute_bridge import bridge_once
from .database import LeadDB


class FakeRemoteClient:
    worker_id = "worker-1"

    def __init__(self):
        self.tasks = {}

    def enqueue(self, payload, task_id=None):
        self.tasks[task_id] = {"status": "queued", "payload": payload, "result": None, "error": ""}
        return {"task_id": task_id}

    def status(self, task_id):
        task = self.tasks[task_id]
        return {"status": task["status"], "payload": task["payload"], "result": task["result"], "error": task["error"]}


def test_remote_bridge_persists_completed_specialist_evidence_before_local_completion():
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = {
            "fingerprint": "lead-1",
            "company": "Example",
            "signal": "We need an AI development team",
        }
        assert db.insert_if_new(lead)
        task = enqueue(db, "ai_demand_discovery", {"lead": lead, "evidence_events": [{"signal": lead["signal"], "source": "test"}]})
        remote = FakeRemoteClient()
        first = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        assert first["published"]["published_count"] == 1
        local = pending(db, "ai_demand_discovery")
        assert local[0]["status"] == "running"
        remote.tasks[task["task_id"]]["status"] = "completed"
        remote.tasks[task["task_id"]]["result"] = {
            "kind": "agent_task",
            "agent": "ai_demand_discovery",
            "result": {
                "agent": "ai_demand_discovery",
                "role": "discovery_intelligence",
                "fingerprint": "lead-1",
                "matched_event_count": 1,
                "findings": [{"source": "test", "evidence": lead["signal"]}],
            },
        }
        second = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        assert second["reconciled"]["completed_count"] == 1
        assert pending(db, "ai_demand_discovery") == []
        stored = db.get("lead-1")
        assert stored["specialist_findings"]["ai_demand_discovery"]["matched_event_count"] == 1
        assert any(item["agent"] == "ai_demand_discovery" for item in stored["specialist_evidence_events"])
        assert any(item["agent"] == "company_research" for item in pending(db))


class FailingOnceRemoteClient(FakeRemoteClient):
    def __init__(self):
        super().__init__()
        self.fail_once = True

    def enqueue(self, payload, task_id=None):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated remote publish failure")
        return super().enqueue(payload, task_id=task_id)


def test_remote_publication_failure_is_durable_and_retried():
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = {"fingerprint": "lead-2", "company": "Example", "signal": "Hiring an AI team"}
        assert db.insert_if_new(lead)
        task = enqueue(db, "ai_demand_discovery", {"lead": lead, "evidence_events": []})
        remote = FailingOnceRemoteClient()

        first = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        assert first["published_count"] == 0
        publication = db.compute_bridge_get(task["task_id"])
        assert publication["status"] == "publish_retry"
        local = pending(db, "ai_demand_discovery")
        assert local[0]["status"] == "running"

        second = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        assert second["published_count"] == 1
        assert db.compute_bridge_get(task["task_id"])["status"] == "published"
        assert remote.tasks[task["task_id"]]["status"] == "queued"


def test_remote_result_recovery_is_idempotent_if_worker_dies_after_persistence(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = {"fingerprint": "lead-crash-window", "company": "Example", "signal": "Need an engineering team"}
        assert db.insert_if_new(lead)
        task = enqueue(db, "ai_demand_discovery", {"lead": lead, "evidence_events": []})
        remote = FakeRemoteClient()

        first = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        assert first["published_count"] == 1
        remote.tasks[task["task_id"]]["status"] = "completed"
        remote.tasks[task["task_id"]]["result"] = {
            "kind": "agent_task",
            "agent": "ai_demand_discovery",
            "result": {
                "agent": "ai_demand_discovery",
                "role": "discovery_intelligence",
                "fingerprint": "lead-crash-window",
                "matched_event_count": 1,
                "findings": [{"source": "test", "evidence": lead["signal"]}],
            },
        }

        original_complete = __import__("lead_engine.compute_bridge", fromlist=["complete"]).complete
        def crash_after_persistence(*args, **kwargs):
            raise RuntimeError("simulated worker death after durable result publication")
        monkeypatch.setattr("lead_engine.compute_bridge.complete", crash_after_persistence)

        try:
            bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected simulated worker death")

        stored_after_crash = db.get("lead-crash-window")
        events_after_crash = [item for item in stored_after_crash["specialist_evidence_events"] if item.get("agent") == "ai_demand_discovery"]
        assert len(events_after_crash) == 1
        assert pending(db, "company_research")
        assert pending(db, "ai_demand_discovery")[0]["status"] == "running"

        monkeypatch.setattr("lead_engine.compute_bridge.complete", original_complete)
        recovered = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)
        assert recovered["completed_count"] == 1
        assert pending(db, "ai_demand_discovery") == []
        stored = db.get("lead-crash-window")
        events = [item for item in stored["specialist_evidence_events"] if item.get("agent") == "ai_demand_discovery"]
        assert len(events) == 1
        assert stored["specialist_findings"]["ai_demand_discovery"]["matched_event_count"] == 1
        assert len([item for item in pending(db, "company_research") if item["dedupe_key"] == "company_research:lead-crash-window"]) == 1
