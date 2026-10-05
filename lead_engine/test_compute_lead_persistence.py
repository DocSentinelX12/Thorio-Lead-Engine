import tempfile
from pathlib import Path

from .compute_lead_persistence import lead_compute_once
from .database import LeadDB


class FakeClient:
    worker_id = "gpu-worker-1"
    def __init__(self):
        self.tasks = {}
    def enqueue(self, payload, task_id=None):
        existing = self.tasks.get(task_id)
        if existing is not None:
            if existing["payload"] != payload:
                raise ValueError("different payload")
            return {"task_id": task_id}
        self.tasks[task_id] = {"status": "queued", "payload": payload, "result": None, "error": ""}
        return {"task_id": task_id}
    def status(self, task_id):
        task = self.tasks[task_id]
        return {"status": task["status"], "payload": task["payload"], "result": task["result"], "error": task["error"]}
    def checkpoint_results(self, task_id):
        task = self.tasks[task_id]
        result = task["result"]
        return result if isinstance(result, dict) else {"leads": []}


def test_lead_compute_work_is_durable_and_publishes_back_to_leaddb(tmp_path):
    db = LeadDB(data_dir=Path(tmp_path))
    lead = {"fingerprint": "lead-1", "company": "Example", "signal": "Hiring engineers"}
    assert db.insert_if_new(lead)
    client = FakeClient()

    first = lead_compute_once(db, client, dispatch_limit=10, reconcile_limit=10)
    assert first["dispatched_count"] == 1
    assert db.compute_lead_dispatched(10)[0]["fingerprint"] == "lead-1"

    client.tasks["lead-prepare:lead-1"]["status"] = "completed"
    client.tasks["lead-prepare:lead-1"]["result"] = {
        "kind": "lead_prepare",
        "leads": [{"fingerprint": "lead-1", "company": "Example", "score": 91, "research_status": "prepared"}],
        "count": 1,
    }
    second = lead_compute_once(db, client, dispatch_limit=10, reconcile_limit=10)
    assert second["completed_count"] == 1
    assert db.compute_lead_dispatched(10) == []
    assert db.get("lead-1")["score"] == 91
    assert db.get("lead-1")["research_status"] == "prepared"


def test_lead_compute_retry_does_not_lose_the_original_lead(tmp_path):
    db = LeadDB(data_dir=Path(tmp_path))
    lead = {"fingerprint": "lead-2", "company": "Example"}
    assert db.insert_if_new(lead)
    client = FakeClient()
    lead_compute_once(db, client, dispatch_limit=10, reconcile_limit=10)
    client.tasks["lead-prepare:lead-2"]["status"] = "failed"
    client.tasks["lead-prepare:lead-2"]["error"] = "GPU family unavailable"
    result = lead_compute_once(db, client, dispatch_limit=10, reconcile_limit=10)
    assert result["retried_count"] == 1
    assert db.get("lead-2")["company"] == "Example"
    assert db.compute_lead_dispatched(10)[0]["fingerprint"] == "lead-2"
    assert db.compute_lead_dispatched(10)[0]["attempts"] == 2
