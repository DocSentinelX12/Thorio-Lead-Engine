import pytest

from .agent_orchestrator import AgentOrchestrator
from .agent_queue import enqueue, pending
from .agent_registry import ALL_AGENT_ROLES
from .database import LeadDB


def test_orchestrator_drains_handoffs_created_by_specialists(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = {
        "fingerprint": "orchestrator-drain-test",
        "company": "Acme",
        "signal": "Acme is hiring a remote software engineer",
        "job_title": "Software Engineer",
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Jane Doe",
            "decision_maker_evidence": "Verified company leadership page",
        },
    }
    db.insert_if_new(lead)
    enqueue(db, "qualification_a", {"lead": lead}, priority=10)

    result = AgentOrchestrator(db).run_all_once(limit_per_agent=1)

    assert result["agent_count"] == 34
    assert result["claimed_count"] >= 1
    assert result["completed_count"] >= 1
    assert result["round_count"] >= 2
    assert result["drain_complete"] is True
    assert result["remaining_queue_count"] == 0
    assert not pending(db)


def test_orchestrator_drain_round_limit_is_bounded(tmp_path, monkeypatch):
    db = LeadDB(data_dir=tmp_path)
    lead = {
        "fingerprint": "orchestrator-bound-test",
        "company": "Acme",
        "signal": "Acme is hiring a remote software engineer",
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Jane Doe",
            "decision_maker_evidence": "Verified company leadership page",
        },
    }
    db.insert_if_new(lead)
    enqueue(db, "qualification_a", {"lead": lead}, priority=10)
    monkeypatch.setenv("THORIO_AGENT_DRAIN_ROUNDS", "1")

    result = AgentOrchestrator(db).run_all_once(limit_per_agent=1)

    assert result["round_count"] == 1
    assert result["claimed_count"] == 1
    assert result["drain_complete"] is False
    assert result["remaining_queue_count"] > 0


def test_orchestrator_execution_workers_support_large_production_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_AGENT_EXECUTION_WORKERS", "128")
    db = LeadDB(data_dir=tmp_path)
    orchestrator = AgentOrchestrator(db)

    assert orchestrator._execution_workers() == 128
    assert sum(role.max_concurrency for role in ALL_AGENT_ROLES) >= 128


def test_orchestrator_execution_workers_remain_hard_capped(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_AGENT_EXECUTION_WORKERS", "9999")
    db = LeadDB(data_dir=tmp_path)
    orchestrator = AgentOrchestrator(db)

    assert orchestrator._execution_workers() == 128


def test_orchestrator_rejects_non_positive_agent_limit(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    orchestrator = AgentOrchestrator(db)
    with pytest.raises(ValueError, match="limit_per_agent"):
        orchestrator.run_all_once(limit_per_agent=0)
