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
        assert any(item["agent"] == "qualification_a" for item in pending(db))
