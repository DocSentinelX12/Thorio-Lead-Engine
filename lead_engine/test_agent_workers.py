from datetime import datetime, timedelta, timezone

import pytest

from .agent_orchestrator import AgentOrchestrator
from .agent_specializations import specialization_registry
from .agent_workers import handler_registry, run_worker_once
from .database import LeadDB
from .agent_queue import enqueue


def _db(tmp_path):
    return LeadDB(data_dir=tmp_path)


def _recent():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def test_every_specialist_has_an_executable_handler():
    specializations = specialization_registry()
    handlers = handler_registry()
    assert set(specializations) == set(handlers)
    assert len(handlers) == 20


def test_discovery_worker_only_normalizes_observed_evidence(tmp_path):
    db = _db(tmp_path)
    orchestrator = AgentOrchestrator(db)
    task = orchestrator.dispatch_discovery(
        "x_signal",
        {"source": "x", "signal": "Company is hiring a software engineer", "source_id": "1"},
    )
    result = run_worker_once(db, "x_signal", worker_id="x-worker")
    assert result["completed_count"] == 1
    assert result["failed_count"] == 0
    output = result["results"][0]
    assert output["qualification_performed"] is False
    assert output["record"]["source_id"] == "1"
    assert task["agent"] == "x_signal"


def test_qualification_worker_applies_independent_company_routes(tmp_path):
    db = _db(tmp_path)
    task = enqueue(
        db,
        "qualification_a",
        {
            "lead": {
                "company": "Acme",
                "signal": "Acme is hiring a remote software engineer",
                "job_title": "Software Engineer",
                "need_at": _recent(),
            }
        },
    )
    result = run_worker_once(db, "qualification_a", worker_id="qualification-a")
    assert result["completed_count"] == 1
    lead = result["results"][0]["lead"]
    assert "Thorio" in lead["potential_routes"]
    assert lead["qualification_results"]["Shiftr"]["qualified"] is True
    assert task["agent"] == "qualification_a"


def test_outreach_worker_refuses_unauthorized_action(tmp_path):
    db = _db(tmp_path)
    enqueue(db, "outreach_closer", {"lead": {"company": "Acme"}})
    result = run_worker_once(db, "outreach_closer", worker_id="outreach")
    assert result["failed_count"] == 1
    assert "authorized=True" in result["results"][0]["error"]


def test_orchestrator_rejects_cross_workforce_dispatch(tmp_path):
    db = _db(tmp_path)
    orchestrator = AgentOrchestrator(db)
    with pytest.raises(ValueError):
        orchestrator.dispatch_processing("x_signal", {"record": {}})
    with pytest.raises(ValueError):
        orchestrator.dispatch_discovery("qualification_a", {})


def test_unknown_worker_role_is_rejected(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        run_worker_once(db, "not_a_real_agent", worker_id="worker")


def test_invalid_discovery_evidence_isolated_to_worker(tmp_path):
    db = _db(tmp_path)
    enqueue(db, "reddit_signal", {"record": {"source": "reddit"}})
    result = run_worker_once(db, "reddit_signal", worker_id="reddit-worker")
    assert result["failed_count"] == 1
    assert result["completed_count"] == 0
