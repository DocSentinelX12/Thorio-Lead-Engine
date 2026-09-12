from datetime import datetime, timedelta, timezone

import pytest

from .agent_orchestrator import AgentOrchestrator
from .agent_specializations import specialization_registry
from .agent_workers import handler_registry, run_worker_once
from .database import LeadDB
from .agent_queue import enqueue, pending
from .revenue_execution import register_revenue_transport


def _db(tmp_path):
    return LeadDB(data_dir=tmp_path)


def _recent():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class _FakeTransport:
    def __init__(self):
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"provider": "test", "delivery_id": f"test-{len(self.calls)}", "status": "accepted"}


def test_every_specialist_has_an_executable_handler():
    specializations = specialization_registry()
    handlers = handler_registry()
    assert set(specializations) == set(handlers)
    assert len(handlers) == 34


def test_discovery_worker_only_normalizes_observed_evidence(tmp_path):
    db = _db(tmp_path)
    orchestrator = AgentOrchestrator(db)
    task = orchestrator.dispatch_discovery("x_signal", {"source": "x", "signal": "Company is hiring a software engineer", "source_id": "1"})
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
    assert "company_research" in agents
    assert "qualification_a" not in agents
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
    assert finding["handoff"] == "company_research"
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


def test_qualification_worker_requires_completed_company_research(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "qualification-research-gate", "company": "Acme", "signal": "Acme is hiring a remote software engineer"}
    db.insert_if_new(lead)
    enqueue(db, "qualification_a", {"lead": lead})
    result = run_worker_once(db, "qualification_a", worker_id="qualification-a")
    assert result["completed_count"] == 0
    assert result["failed_count"] == 1
    stored = db.get(lead["fingerprint"])
    assert stored.get("qualification_results") is None


def test_qualification_worker_applies_independent_company_routes_after_research(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "qualification-worker-test", "company": "Acme", "signal": "Acme is hiring a remote software engineer", "job_title": "Software Engineer", "need_at": _recent(), "research_status": "complete", "research_verified_fields": ["company_verified", "decision_maker", "decision_maker_evidence"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_verification_status": "verified"}}
    db.insert_if_new(lead)
    task = enqueue(db, "qualification_a", {"lead": lead})
    result = run_worker_once(db, "qualification_a", worker_id="qualification-a")
    assert result["completed_count"] == 1
    stored = db.get(lead["fingerprint"])
    assert "Thorio" in stored["potential_routes"]
    assert stored["qualification_results"]["Shiftr"]["qualified"] is True
    assert task["agent"] == "qualification_a"


def test_outreach_worker_sends_autonomously_after_sales_eligibility(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "outreach-worker-test", "company": "Acme", "potential_routes": ["Thorio", "Shiftr"], "qualified": True, "sales_eligibility": "eligible", "signal": "Acme is hiring a remote software engineer", "research_status": "complete", "company_research": {"decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "contact_email": "taylor@example.com"}, "evidence_events": [{"source_id": "evt-1", "source_url": "https://example.com/signal", "signal": "Acme is hiring a remote software engineer"}]}
    db.insert_if_new(lead)
    enqueue(db, "outreach_closer", {"lead": lead})
    transport = _FakeTransport()
    register_revenue_transport(transport)
    try:
        result = run_worker_once(db, "outreach_closer", worker_id="outreach-autonomous")
    finally:
        register_revenue_transport(None)
    assert result["completed_count"] == 1
    assert result["failed_count"] == 0
    output = result["results"][0]
    assert output["autonomous"] is True
    assert output["approval_required"] is False
    assert output["action"] == "send_outreach"
    assert output["route"] in {"thorio", "shiftr"}
    assert "Acme" in output["body"]
    assert "remote software engineer" in output["body"]
    assert "Hi Taylor" in output["body"]
    assert len(transport.calls) == 1
    stored = db.get(lead["fingerprint"])
    assert stored["outreach_state"] == "awaiting_response"
    assert stored["revenue_lifecycle_state"] == "outreach_sent"
    assert stored["last_outreach_action_id"]


def test_follow_up_is_autonomous_after_observed_outcome(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "follow-up-persistence-test", "company": "Acme", "qualified": True, "sales_eligibility": "eligible", "signal": "Acme is hiring a remote software engineer", "business_need": "remote software engineer hiring", "research_status": "complete", "company_research": {"decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_email": "taylor@example.com", "decision_maker_verification_status": "verified"}, "outreach_route": "Thorio", "outreach_state": "awaiting_response", "outreach_history": [{"at": _recent(), "outcome": "sent"}], "outreach_attempt": 1, "conversation_id": "conversation:follow-up-persistence-test:thorio", "contact_email": "taylor@example.com"}
    db.insert_if_new(lead)
    enqueue(db, "follow_up", {"lead": lead, "outcome": "no_response", "execute": True})
    transport = _FakeTransport()
    register_revenue_transport(transport)
    try:
        result = run_worker_once(db, "follow_up", worker_id="follow-up-worker")
    finally:
        register_revenue_transport(None)
    assert result["completed_count"] == 1
    assert result["failed_count"] == 0
    output = result["results"][0]
    assert output["autonomous"] is True
    assert output["approval_required"] is False
    assert output["action"] == "send_follow_up"
    assert len(transport.calls) == 1
    stored = db.get(lead["fingerprint"])
    assert stored["outreach_state"] == "awaiting_response"
    assert stored["outreach_attempt"] == 2
    assert stored["next_follow_up_at"] is not None
    assert stored["follow_up_due"] is True
    assert len(stored["outreach_history"]) == 3
    assert stored["outreach_history"][-1]["kind"] == "follow_up"
    assert stored["outreach_history"][-1]["status"] == "sent"


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