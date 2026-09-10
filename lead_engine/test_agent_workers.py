from datetime import datetime, timedelta, timezone

import pytest

from .agent_orchestrator import AgentOrchestrator
from .agent_specializations import specialization_registry
from .agent_workers import handler_registry, run_worker_once
from .database import LeadDB
from .agent_queue import enqueue, pending


def _db(tmp_path):
    return LeadDB(data_dir=tmp_path)


def _recent():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def test_every_specialist_has_an_executable_handler():
    specializations = specialization_registry()
    handlers = handler_registry()
    assert set(specializations) == set(handlers)
    assert len(handlers) == 34


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


def test_social_source_discovery_handoffs_to_social_research(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "social-handoff-test", "company": "Acme", "signal": "Acme is hiring a CTO", "source": "linkedin"}
    db.insert_if_new(lead)
    AgentOrchestrator(db).dispatch_discovery("linkedin_signal", {**lead, "evidence": "Acme is hiring a CTO", "source_id": "social-1"})
    result = run_worker_once(db, "linkedin_signal", worker_id="linkedin-worker")
    assert result["completed_count"] == 1
    queued = pending(db)
    agents = {task["agent"] for task in queued}
    assert "qualification_a" in agents
    assert "social_intelligence" in agents
    assert "social_hiring_research" in agents
    assert "social_decision_maker_research" in agents
    assert "social_inquiry_research" in agents
    assert "social_company_context" in agents


def test_advanced_discovery_specialist_extracts_evidence_without_qualifying(tmp_path):
    db = _db(tmp_path)
    orchestrator = AgentOrchestrator(db)
    task = orchestrator.dispatch_discovery("engineering_demand_discovery", {"lead": {"fingerprint": "d1", "company": "Acme"}, "evidence_events": [{"source": "linkedin", "signal": "Acme is hiring a backend engineer", "observed_at": _recent()}]})
    result = run_worker_once(db, "engineering_demand_discovery", worker_id="engineering-worker")
    assert result["completed_count"] == 1
    finding = result["results"][0]
    assert finding["matched_event_count"] == 1
    assert finding["requires_verification"] is True
    assert finding["handoff"] == "qualification_a"
    assert task["agent"] == "engineering_demand_discovery"


def test_social_research_handoffs_to_company_research(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "social-research-handoff", "company": "Acme"}
    db.insert_if_new(lead)
    AgentOrchestrator(db).dispatch_social_research("social_decision_maker_research", {"lead": lead, "evidence_events": [{"source": "linkedin", "signal": "Taylor is CTO at Acme", "observed_at": _recent()}]})
    result = run_worker_once(db, "social_decision_maker_research", worker_id="social-worker")
    assert result["completed_count"] == 1
    output = result["results"][0]
    assert output["matched_event_count"] == 1
    assert output["fabricated_fields"] == []
    assert output["verification_required"] is True
    assert output["handoff"] == "company_research"
    assert any(task["agent"] == "company_research" for task in pending(db))


def test_qualification_worker_applies_independent_company_routes(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "qualification-worker-test", "company": "Acme", "signal": "Acme is hiring a remote software engineer", "job_title": "Software Engineer", "need_at": _recent()}
    db.insert_if_new(lead)
    task = enqueue(db, "qualification_a", {"lead": lead})
    result = run_worker_once(db, "qualification_a", worker_id="qualification-a")
    assert result["completed_count"] == 1
    stored = db.get(lead["fingerprint"])
    assert "Thorio" in stored["potential_routes"]
    assert stored["qualification_results"]["Shiftr"]["qualified"] is True
    assert task["agent"] == "qualification_a"


def test_outreach_worker_requires_explicit_authorization(tmp_path):
    db = _db(tmp_path)
    lead = {
        "fingerprint": "outreach-worker-test",
        "company": "Acme",
        "potential_routes": ["Thorio", "Shiftr"],
        "signal": "Acme is hiring a remote software engineer",
        "research_status": "complete",
        "company_research": {
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "contact_email": "taylor@example.com",
        },
        "evidence_events": [{"source_id": "evt-1", "source_url": "https://example.com/signal"}],
    }
    db.insert_if_new(lead)
    enqueue(db, "outreach_closer", {"lead": lead})
    blocked = run_worker_once(db, "outreach_closer", worker_id="outreach-blocked")
    assert blocked["completed_count"] == 0
    assert blocked["failed_count"] == 1

    enqueue(db, "outreach_closer", {"lead": lead, "authorized": True})
    result = run_worker_once(db, "outreach_closer", worker_id="outreach-authorized")
    assert result["completed_count"] == 1
    assert result["failed_count"] == 0
    output = result["results"][0]
    assert output["autonomous"] is True
    assert output["authorized"] is True
    assert output["action"] == "prepare_authorized_outreach"
    assert output["route"] in {"Thorio", "Shiftr"}
    assert output["evidence_refs"] == ["https://example.com/signal", "https://example.com/taylor"]
    assert "Acme is hiring a remote software engineer" in output["body"]


def test_company_research_does_not_mark_observed_person_as_verified_decision_maker(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "research-verification-test", "company": "Acme", "person": "Taylor", "signal": "Acme is hiring a backend engineer"}
    db.insert_if_new(lead)
    enqueue(db, "company_research", {"lead": lead, "evidence_events": [{"source": "linkedin", "signal": "Taylor is mentioned by Acme"}]})
    result = run_worker_once(db, "company_research", worker_id="research-worker")
    assert result["completed_count"] == 1
    stored = db.get(lead["fingerprint"])
    assert stored["research_status"] == "research_required"
    assert stored["company_research"]["decision_maker_verification_status"] == "observed_needs_role_verification"


def test_orchestrator_rejects_cross_workforce_dispatch(tmp_path):
    db = _db(tmp_path)
    orchestrator = AgentOrchestrator(db)
    with pytest.raises(ValueError):
        orchestrator.dispatch_processing("x_signal", {"record": {}})
    with pytest.raises(ValueError):
        orchestrator.dispatch_discovery("qualification_a", {})
    with pytest.raises(ValueError):
        orchestrator.dispatch_social_research("qualification_a", {})


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
