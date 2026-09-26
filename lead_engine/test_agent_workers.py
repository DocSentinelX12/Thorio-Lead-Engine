from datetime import datetime, timedelta, timezone

import pytest

from .agent_orchestrator import AgentOrchestrator
from .agent_specializations import specialization_registry
from .agent_workers import handler_registry, run_worker_once
from .database import LeadDB
from .agent_queue import enqueue, pending
from .revenue_execution import register_revenue_transport
from .research_intelligence import build_research_intelligence
from .sales_handoff import package_digest


def _db(tmp_path): return LeadDB(data_dir=tmp_path)
def _recent(): return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

class _FakeTransport:
    def __init__(self): self.calls = []
    def send(self, **kwargs):
        self.calls.append(dict(kwargs)); return {"provider": "test", "delivery_id": f"test-{len(self.calls)}", "status": "accepted"}


def test_every_specialist_has_an_executable_handler():
    assert set(specialization_registry()) == set(handler_registry()); assert len(handler_registry()) == 35

def test_discovery_worker_only_normalizes_observed_evidence(tmp_path):
    db = _db(tmp_path); orchestrator = AgentOrchestrator(db); task = orchestrator.dispatch_discovery("x_signal", {"source": "x", "signal": "Company is hiring a software engineer", "source_id": "1"}); result = run_worker_once(db, "x_signal", worker_id="x-worker")
    assert result["completed_count"] == 1 and result["failed_count"] == 0; assert result["results"][0]["qualification_performed"] is False; assert result["results"][0]["record"]["source_id"] == "1"; assert task["agent"] == "x_signal"

def test_social_source_discovery_handoffs_to_social_research(tmp_path):
    db = _db(tmp_path); lead = {"fingerprint": "social-handoff-test", "company": "Acme", "signal": "Acme is hiring a CTO", "source": "linkedin"}; db.insert_if_new(lead); AgentOrchestrator(db).dispatch_discovery("linkedin_signal", {**lead, "evidence": "Acme is hiring a CTO", "source_id": "social-1"}); result = run_worker_once(db, "linkedin_signal", worker_id="linkedin-worker")
    agents = {task["agent"] for task in pending(db)}; assert result["completed_count"] == 1; assert "company_research" in agents; assert "qualification_a" not in agents; assert {"social_intelligence", "social_hiring_research", "social_decision_maker_research", "social_inquiry_research", "social_company_context"}.issubset(agents)

def test_advanced_discovery_specialist_extracts_evidence_without_qualifying(tmp_path):
    db = _db(tmp_path); task = AgentOrchestrator(db).dispatch_discovery("engineering_demand_discovery", {"lead": {"fingerprint": "d1", "company": "Acme"}, "evidence_events": [{"source": "linkedin", "signal": "Acme is hiring a backend engineer", "observed_at": _recent()}]}); result = run_worker_once(db, "engineering_demand_discovery", worker_id="engineering-worker")
    finding = result["results"][0]; assert result["completed_count"] == 1; assert finding["matched_event_count"] == 1 and finding["requires_verification"] is True and finding["handoff"] == "company_research"; assert task["agent"] == "engineering_demand_discovery"

def test_social_research_handoffs_to_company_research(tmp_path):
    db = _db(tmp_path); lead = {"fingerprint": "social-research-handoff", "company": "Acme"}; db.insert_if_new(lead); AgentOrchestrator(db).dispatch_social_research("social_decision_maker_research", {"lead": lead, "evidence_events": [{"source": "linkedin", "signal": "Taylor is CTO at Acme", "observed_at": _recent()}]}); result = run_worker_once(db, "social_decision_maker_research", worker_id="social-worker")
    output = result["results"][0]; assert result["completed_count"] == 1; assert output["matched_event_count"] == 1 and output["fabricated_fields"] == [] and output["verification_required"] is True and output["handoff"] == "company_research"; assert any(task["agent"] == "company_research" for task in pending(db))

def test_qualification_worker_requires_completed_company_research(tmp_path):
    db = _db(tmp_path); lead = {"fingerprint": "qualification-research-gate", "company": "Acme", "signal": "Acme is hiring a remote software engineer"}; db.insert_if_new(lead); enqueue(db, "qualification_a", {"lead": lead}); result = run_worker_once(db, "qualification_a", worker_id="qualification-a"); assert result["completed_count"] == 0 and result["failed_count"] == 1; assert db.get(lead["fingerprint"]).get("qualification_results") is None



def test_qualification_b_materializes_blocked_sales_state_before_airtable_handoff(tmp_path):
    db = _db(tmp_path)
    now = _recent()
    lead = {
        "fingerprint": "qualification-sales-boundary",
        "company": "Acme",
        "qualified": False,
        "research_status": "complete",
        "business_need": "remote software engineer hiring",
        "need_at": now,
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
        },
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "remote software engineer hiring", "evidence": ["https://example.com/need"]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence_url": "https://example.com/need"},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/hiring"]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/commercial"]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Current remote software engineering hiring need."}}},
        "research_verified_fields": ["business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research", "route_research"],
    }
    db.insert_if_new(lead)
    enqueue(db, "qualification_b", {"lead": lead, "prior_result": {"agent": "qualification_a"}}, priority=9)
    try:
        result = run_worker_once(db, "qualification_b", worker_id="qualification-sales-boundary-worker")
        stored = db.get(lead["fingerprint"])
        assert result["failed_count"] == 0, result
        assert stored["qualified"] is True
        assert stored["sales_eligibility"] == "blocked"
        assert stored["sales_eligibility_reason"] == "research_verification_pending"
        assert stored["revenue_lifecycle_state"] == "qualified"
    finally:
        db.close()

def test_qualification_worker_applies_independent_company_routes_after_research(tmp_path):
    db = _db(tmp_path); now = _recent(); lead = {"fingerprint": "qualification-worker-test", "company": "Acme", "signal": "Acme is hiring a remote software engineer", "job_title": "Software Engineer", "need_at": now, "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_verification_status": "verified", "decision_maker_email": "taylor@example.com"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "Acme is hiring a remote software engineer and is looking for an engineering team to develop software.", "observed_at": now, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Current engineering hiring need."}, "Shiftr": {"verified": True, "verification_status": "verified", "evidence": "Current need for an engineering team to develop software."}, "Paxus": {"verified": False, "evidence": ""}}}}
    db.insert_if_new(lead); task = enqueue(db, "qualification_a", {"lead": lead}); result = run_worker_once(db, "qualification_a", worker_id="qualification-a"); stored = db.get(lead["fingerprint"]); assert result["completed_count"] == 1; assert "Thorio" in stored["potential_routes"] and "Shiftr" in stored["potential_routes"]; assert task["agent"] == "qualification_a"

def test_outreach_worker_sends_autonomously_after_sales_eligibility(tmp_path):
    db = _db(tmp_path); now = _recent(); route_results = {"Thorio": {"qualified": True, "route_research": {"verified": True, "evidence": [{"url": "https://example.com/route", "evidence": "Current software engineering hiring need.", "observed_at": _recent(), "verification_status": "verified"}]}}, "Shiftr": {"qualified": True, "route_research": {"verified": True, "evidence": "Current engineering support need."}}}; lead = {"fingerprint": "outreach-worker-test", "company": "Acme", "potential_routes": ["Thorio", "Shiftr"], "eligible_routes": ["Thorio", "Shiftr"], "preserved_routes": ["Thorio", "Shiftr"], "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}, "qualified": True, "sales_eligibility": "eligible", "signal": "Acme is hiring a remote software engineer", "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "contact_email": "taylor@example.com", "decision_maker_verification_status": "verified"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Current software engineering hiring need.", "observed_at": _recent(), "verification_status": "verified"}]}, "Shiftr": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/shiftr", "evidence": "Current engineering support need.", "observed_at": _recent(), "verification_status": "verified"}]}}}, "qualification_results": route_results, "evidence_events": [{"source_id": "evt-1", "source_url": "https://example.com/signal", "signal": "Acme is hiring a remote software engineer"}], "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "remote software engineer hiring", "evidence": [{"url": "https://example.com/need", "evidence": "Current software engineering hiring need.", "observed_at": _recent(), "verification_status": "verified"}]}, "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Current software engineering hiring.", "observed_at": _recent(), "verification_status": "verified"}]}, "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Current commercial context.", "observed_at": _recent(), "verification_status": "verified"}]}, "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Current software engineering hiring need.", "observed_at": _recent(), "verification_status": "verified"}]}}; lead["research_intelligence"] = build_research_intelligence(lead); db.insert_if_new(lead); db.record_airtable_handoff(lead["fingerprint"], package_digest(lead), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00"); enqueue(db, "outreach_closer", {"lead": lead}); transport = _FakeTransport(); register_revenue_transport(transport)
    try: result = run_worker_once(db, "outreach_closer", worker_id="outreach-autonomous")
    finally: register_revenue_transport(None)
    output = result["results"][0]; stored = db.get(lead["fingerprint"]); assert result["completed_count"] == 1 and result["failed_count"] == 0; assert output["autonomous"] is True and output["approval_required"] is False and output["action"] == "send_outreach"; assert output["route"] in {"thorio", "shiftr"}; assert "Acme" in output["body"] and "remote software engineer" in output["body"] and "Hi Taylor" in output["body"]; assert len(transport.calls) == 1; assert stored["outreach_state"] == "awaiting_response" and stored["revenue_lifecycle_state"] == "outreach_sent" and stored["last_outreach_action_id"]

def test_follow_up_is_autonomous_after_observed_outcome(tmp_path):
    db = _db(tmp_path); now = _recent(); lead = {"fingerprint": "follow-up-persistence-test", "company": "Acme", "qualified": True, "sales_eligibility": "eligible", "signal": "Acme is hiring a remote software engineer", "business_need": "remote software engineer hiring", "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_email": "taylor@example.com", "decision_maker_verification_status": "verified"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Current software engineering hiring need."}}}, "qualification_results": {"Thorio": {"qualified": True, "route_research": {"verified": True, "evidence": "Current software engineering hiring need."}}}, "outreach_route": "Thorio", "outreach_state": "awaiting_response", "outreach_history": [{"at": _recent(), "outcome": "sent"}], "outreach_attempt": 1, "conversation_id": "conversation:follow-up-persistence-test:thorio", "contact_email": "taylor@example.com"}; db.insert_if_new(lead); enqueue(db, "follow_up", {"lead": lead, "outcome": "no_response", "execute": True, "authorized": True, "authorized_by_role": "high_ticket_sales_closer"}); transport = _FakeTransport(); register_revenue_transport(transport)
    try: result = run_worker_once(db, "follow_up", worker_id="follow-up-worker")
    finally: register_revenue_transport(None)
    output = result["results"][0]; stored = db.get(lead["fingerprint"]); assert result["completed_count"] == 1 and result["failed_count"] == 0; assert output["autonomous"] is True and output["approval_required"] is False and output["action"] == "send_follow_up"; assert len(transport.calls) == 1; assert stored["outreach_state"] == "awaiting_response" and stored["outreach_attempt"] == 2 and stored["next_follow_up_at"] is not None and stored["follow_up_due"] is True and len(stored["outreach_history"]) == 3 and stored["outreach_history"][-1]["kind"] == "follow_up" and stored["outreach_history"][-1]["status"] == "sent"

def test_company_research_persists_research_intelligence_handoff(tmp_path):
    db = _db(tmp_path)
    lead = {"fingerprint": "research-intelligence-worker", "company": "Acme", "signal": "Acme is hiring a backend engineer"}
    db.insert_if_new(lead)
    enqueue(db, "company_research", {"lead": lead, "evidence_events": [{"source": "linkedin", "signal": "Acme is hiring a backend engineer"}]})
    result = run_worker_once(db, "company_research", worker_id="research-intelligence-worker")
    stored = db.get(lead["fingerprint"])
    assert result["completed_count"] == 1 and result["failed_count"] == 0
    intelligence = stored["research_intelligence"]
    assert intelligence["opportunity_id"] == lead["fingerprint"]
    assert intelligence["fingerprint"] == lead["fingerprint"]
    assert "evidence_graph" in intelligence and "claims" in intelligence


def test_company_research_does_not_mark_observed_person_as_verified_decision_maker(tmp_path):
    db = _db(tmp_path); lead = {"fingerprint": "research-verification-test", "company": "Acme", "person": "Taylor", "signal": "Acme is hiring a backend engineer"}; db.insert_if_new(lead); enqueue(db, "company_research", {"lead": lead, "evidence_events": [{"source": "linkedin", "signal": "Taylor is mentioned by Acme"}]}); result = run_worker_once(db, "company_research", worker_id="research-worker"); stored = db.get(lead["fingerprint"]); assert result["completed_count"] == 1; assert stored["research_status"] == "research_required" and stored["company_research"]["decision_maker_verification_status"] == "observed_needs_role_verification"

def test_orchestrator_rejects_cross_workforce_dispatch(tmp_path):
    db = _db(tmp_path); orchestrator = AgentOrchestrator(db)
    with pytest.raises(ValueError): orchestrator.dispatch_processing("x_signal", {"record": {}})
    with pytest.raises(ValueError): orchestrator.dispatch_discovery("qualification_a", {})
    with pytest.raises(ValueError): orchestrator.dispatch_social_research("qualification_a", {})

def test_unknown_worker_role_is_rejected(tmp_path):
    with pytest.raises(ValueError): run_worker_once(_db(tmp_path), "not_a_real_agent", worker_id="worker")

def test_invalid_discovery_evidence_isolated_to_worker(tmp_path):
    db = _db(tmp_path); enqueue(db, "reddit_signal", {"record": {"source": "reddit"}}); result = run_worker_once(db, "reddit_signal", worker_id="reddit-worker"); assert result["failed_count"] == 1 and result["completed_count"] == 0
