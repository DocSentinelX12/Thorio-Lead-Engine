import tempfile
from pathlib import Path

from .agent_queue import claim_task, enqueue, pending
from .compute_bridge import REMOTE_SAFE_AGENTS, bridge_once, publish_remote_work
from .advanced_agent_logic import DISCOVERY_TARGETS, SOCIAL_TARGETS
from .compute_worker import ComputeWorkerError
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


def test_remote_bridge_only_publishes_stateless_agents_supported_by_remote_worker():
    supported = frozenset(set(DISCOVERY_TARGETS) | set(SOCIAL_TARGETS))
    assert REMOTE_SAFE_AGENTS == supported
    assert "company_research" not in REMOTE_SAFE_AGENTS
    assert "x_signal" not in REMOTE_SAFE_AGENTS
    assert "priority" not in REMOTE_SAFE_AGENTS
    assert "verification" not in REMOTE_SAFE_AGENTS
    assert "routing" not in REMOTE_SAFE_AGENTS
    assert "airtable_integrity" not in REMOTE_SAFE_AGENTS
    assert "outreach_closer" not in REMOTE_SAFE_AGENTS
    assert "follow_up" not in REMOTE_SAFE_AGENTS



class FailingRemoteClient(FakeRemoteClient):
    def __init__(self):
        super().__init__()
        self.enqueue_calls = 0
        self.status_calls = 0

    def enqueue(self, payload, task_id=None):
        self.enqueue_calls += 1
        raise ComputeWorkerError("coordinator unavailable: timeout")

    def status(self, task_id):
        self.status_calls += 1
        raise ComputeWorkerError("coordinator unavailable: timeout")


def test_remote_publish_failure_is_bounded_and_releases_task_for_local_work():
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        for index in range(3):
            lead = {
                "fingerprint": f"failure-lead-{index}",
                "company": f"Example {index}",
                "signal": "We need an AI development team",
            }
            assert db.insert_if_new(lead)
            enqueue(db, "ai_demand_discovery", {"lead": lead, "evidence_events": []})

        remote = FailingRemoteClient()
        result = publish_remote_work(db, remote, limit=10)

        assert result["status"] == "degraded"
        assert result["attempted_count"] == 1
        assert result["prepared_count"] == 1
        assert result["published_count"] == 0
        assert len(result["errors"]) == 1
        assert remote.enqueue_calls == 1
        tasks = pending(db, "ai_demand_discovery")
        assert len(tasks) == 3
        assert all(task["status"] == "queued" for task in tasks)
        failed_task_id = result["errors"][0]["task_id"]
        publication = db.compute_bridge_get(failed_task_id)
        assert publication["status"] == "publish_retry"


def test_remote_status_failure_degrades_without_scanning_or_publishing_more_work():
    with tempfile.TemporaryDirectory() as directory:
        db = LeadDB(data_dir=Path(directory))
        lead = {
            "fingerprint": "status-failure-lead",
            "company": "Example",
            "signal": "We need an AI development team",
        }
        assert db.insert_if_new(lead)
        task = enqueue(db, "ai_demand_discovery", {"lead": lead, "evidence_events": []})
        worker_id = "remote-compute:worker-1"
        db.compute_bridge_prepare(
            task["task_id"],
            worker_id,
            {"kind": "agent_task", "agent": "ai_demand_discovery", "payload": {"lead": lead}},
            "2026-10-10T00:00:00+00:00",
        )
        claim_task(db, task["task_id"], worker_id=worker_id, lease_seconds=900)
        db.compute_bridge_mark_published(task["task_id"], "2026-10-10T00:00:00+00:00")

        remote = FailingRemoteClient()
        result = bridge_once(db, remote, publish_limit=10, reconcile_limit=10)

        assert result["status"] == "degraded"
        assert result["reconciled"]["attempted_count"] == 1
        assert len(result["reconciled"]["errors"]) == 1
        assert remote.status_calls == 1
        assert remote.enqueue_calls == 0
        assert pending(db, "ai_demand_discovery")[0]["status"] == "running"
