import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from .agent_stateful_handlers import routing
from .agent_workers import AgentExecutionContext, execute_task
from .database import LeadDB
from .lead_routes import route_leads


def _db():
    directory = tempfile.TemporaryDirectory()
    db = LeadDB(data_dir=Path(directory.name))
    return directory, db


def test_routing_preserves_all_matching_destinations():
    lead = {"fingerprint": "multi-route", "potential_routes": ["Shiftr", "Paxus", "Thorio"], "verified": True}
    routed = route_leads([lead])
    assert [len(routed[name]) for name in ("Shiftr", "Paxus", "Thorio")] == [1, 1, 1]
    assert not routed["Review"]


def test_routing_requires_final_verification():
    directory, db = _db()
    try:
        with pytest.raises(ValueError, match="verified=True"):
            routing("routing", {"lead": {"fingerprint": "unverified", "potential_routes": ["Thorio"]}}, SimpleNamespace(db=db))
    finally:
        db.close()
        directory.cleanup()


def test_stateful_execution_persists_result_before_completion():
    directory, db = _db()
    try:
        lead = {"fingerprint": "priority-persist", "company": "Example", "signal": "hiring"}
        assert db.insert_if_new(lead)
        from .agent_queue import enqueue
        task = enqueue(db, "priority", {"lead": lead})
        execution = execute_task(db, task, worker_id="test-worker")
        assert execution.status == "complete"
        stored = db.get("priority-persist")
        assert stored is not None
        assert stored["fingerprint"] == "priority-persist"
        assert db.get_state("agent_work_queue")["items"][task["task_id"]]["status"] == "complete"
    finally:
        db.close()
        directory.cleanup()
