from datetime import datetime, timezone

import pytest

from .agent_queue import pending, enqueue
from .agent_workers import run_worker_once
from .database import LeadDB
from .revenue_conversation import record_inbound_event
from .revenue_execution import register_revenue_transport

class FakeTransport:
    def __init__(self): self.calls = []
    def send(self, **kwargs): self.calls.append(dict(kwargs)); return {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}
    def reconcile(self, *, idempotency_key): return None

def _lead(fingerprint="conversation-test"):
    now = datetime.now(timezone.utc).isoformat()
    return {"fingerprint": fingerprint, "company": "Acme", "contact_email": "taylor@example.com", "signal": "Acme needs a remote engineering team", "business_need": "remote engineering team", "qualified": True, "potential_routes": ["Shiftr", "Paxus"], "preserved_routes": ["Shiftr", "Paxus"], "eligible_routes": ["Shiftr", "Paxus"], "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_email": "taylor@example.com", "decision_maker_verification_status": "verified", "company_verification_evidence": ["https://example.com/company"]}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote engineering team", "observed_at": now, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Shiftr": {"verified": True, "verification_status": "verified", "evidence": "Acme needs a remote engineering team."}, "Paxus": {"verified": True, "verification_status": "verified", "evidence": "Acme has a current technology staffing need."}}}, "qualification_results": {"Shiftr": {"qualified": True, "route_research": {"verified": True, "evidence": "Acme needs a remote engineering team."}}, "Paxus": {"qualified": True, "true_referral": True, "route_research": {"verified": True, "evidence": "Acme has a current technology staffing need."}}}, "outreach_route": "Shiftr", "outreach_state": "awaiting_response", "outreach_attempt": 1, "outreach_history": [{"action_id": "a1"}], "conversation_id": f"conversation:{fingerprint}:shiftr"}

def test_follow_up_cannot_be_queued_without_closer_authorization(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead("authorization-test"); db.insert_if_new(lead)
    with pytest.raises(ValueError, match="high_ticket_sales_closer"): enqueue(db, "follow_up", {"lead": lead, "outcome": "no_response", "execute": True})
    assert pending(db, "follow_up") == []

def test_inbound_response_is_durable_and_idempotent(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead(); db.insert_if_new(lead)
    first = record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-1", text="Yes, I am interested", outcome="interested"); second = record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-1", text="Yes, I am interested", outcome="interested")
    stored = db.get(lead["fingerprint"]); assert len(first["events"]) == 1 and len(second["events"]) == 1 and stored["response_count"] == 1 and stored["revenue_lifecycle_state"] == "conversation_active"; assert len(pending(db, "follow_up")) == 1 and pending(db, "follow_up")[0]["payload"]["authorized_by_role"] == "high_ticket_sales_closer"

def test_objection_follow_up_is_executed_by_closer_and_persisted(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead("objection-test"); db.insert_if_new(lead); transport = FakeTransport(); register_revenue_transport(transport)
    try:
        record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-2", text="What does this cost?", outcome="objection", objection="What does this cost?"); result = run_worker_once(db, "follow_up", worker_id="followup-worker")
        assert result["completed_count"] == 1 and result["failed_count"] == 0 and len(transport.calls) == 1
        stored = db.get(lead["fingerprint"]); assert stored["revenue_lifecycle_state"] == "conversation_active" and stored["outreach_state"] == "awaiting_response" and stored["follow_up_due"] is True and stored["next_follow_up_at"] and len(stored["outreach_history"]) == 3
    finally: register_revenue_transport(None)

def test_opt_out_is_terminal_and_never_sends(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead("optout-test"); db.insert_if_new(lead); transport = FakeTransport(); register_revenue_transport(transport)
    try:
        record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-3", text="Please stop contacting me", outcome="opted_out"); stored = db.get(lead["fingerprint"]); assert pending(db, "follow_up") == [] and stored["revenue_lifecycle_state"] == "closed_lost" and stored["next_follow_up_at"] is None and transport.calls == []
    finally: register_revenue_transport(None)

def test_conversation_can_switch_to_preserved_route(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead("switch-test"); db.insert_if_new(lead); record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-4", text="We need to hire ten engineers and want a staffing partner", outcome="interested", suggested_route="Paxus"); stored = db.get(lead["fingerprint"]); assert stored["outreach_route"] == "Paxus" and stored["route_switch_history"][0]["from"] == "Shiftr" and stored["route_switch_history"][0]["to"] == "Paxus" and "hire ten engineers" in stored["route_switch_history"][0]["evidence_text"]


def test_completed_commercial_response_becomes_durable_conversion(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("conversion-test")
    db.insert_if_new(lead)

    result = record_inbound_event(
        db,
        opportunity_id=lead["fingerprint"],
        conversation_id=lead["conversation_id"],
        event_id="evt-convert",
        text="We signed the contract and are ready to start.",
    )

    stored = db.get(lead["fingerprint"])
    assert result["events"][-1]["outcome"] == "converted"
    assert stored["revenue_lifecycle_state"] == "converted"
    assert stored["outreach_state"] == "converted"
    assert stored["next_follow_up_at"] is None
    assert stored["follow_up_due"] is False
    assert stored["commercial_outcome"]["type"] == "converted"
    assert stored["commercial_outcome"]["evidence"] == "We signed the contract and are ready to start."
    assert pending(db, "follow_up") == []


def test_referred_outcome_requires_durable_referral_submission(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("referred-test")
    db.insert_if_new(lead)

    with pytest.raises(ValueError, match="referral submission"):
        record_inbound_event(
            db,
            opportunity_id=lead["fingerprint"],
            conversation_id=lead["conversation_id"],
            event_id="evt-referral-invalid",
            text="Please connect me with Paxus.",
            outcome="referred",
        )

    lead["referral_submitted"] = True
    db.update_payload(lead["fingerprint"], lead)
    result = record_inbound_event(
        db,
        opportunity_id=lead["fingerprint"],
        conversation_id=lead["conversation_id"],
        event_id="evt-referral-valid",
        text="Please connect me with Paxus.",
        outcome="referred",
    )
    stored = db.get(lead["fingerprint"])
    assert result["events"][-1]["outcome"] == "referred"
    assert stored["revenue_lifecycle_state"] == "referred"
    assert stored["commercial_outcome"]["type"] == "referred"
    assert pending(db, "follow_up") == []


def test_route_switch_is_rejected_when_conversation_lacks_candidate_evidence(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("switch-evidence-test")
    db.insert_if_new(lead)

    record_inbound_event(
        db,
        opportunity_id=lead["fingerprint"],
        conversation_id=lead["conversation_id"],
        event_id="evt-switch-no-evidence",
        text="Thanks, sounds good.",
        outcome="interested",
        suggested_route="Paxus",
    )

    stored = db.get(lead["fingerprint"])
    assert stored["outreach_route"] == "Shiftr"
    assert stored["route_switch_history"] == []
    assert stored["conversation_events"][-1]["warnings"] == ["route_switch_evidence_not_verified"]


def test_route_switch_requires_independently_qualified_candidate(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("switch-qualification-test")
    lead["qualification_results"]["Paxus"]["qualified"] = False
    db.insert_if_new(lead)

    record_inbound_event(
        db,
        opportunity_id=lead["fingerprint"],
        conversation_id=lead["conversation_id"],
        event_id="evt-switch-unqualified",
        text="We need to hire ten engineers and want a staffing partner",
        outcome="interested",
        suggested_route="Paxus",
    )

    stored = db.get(lead["fingerprint"])
    assert stored["outreach_route"] == "Shiftr"
    assert stored["route_switch_history"] == []
    assert stored["conversation_events"][-1]["warnings"] == ["route_switch_candidate_not_qualified"]
