from datetime import datetime, timedelta, timezone

from .agent_queue import pending
from .agent_workers import run_worker_once
from .database import LeadDB
from .revenue_conversation import record_inbound_event
from .revenue_execution import register_revenue_transport


class FakeTransport:
    def __init__(self):
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}

    def reconcile(self, *, idempotency_key):
        return None


def _lead(fingerprint="conversation-test"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": fingerprint,
        "company": "Acme",
        "contact_email": "taylor@example.com",
        "signal": "Acme needs a remote engineering team",
        "business_need": "remote engineering team",
        "qualified": True,
        "potential_routes": ["Shiftr", "Paxus"],
        "preserved_routes": ["Shiftr", "Paxus"],
        "eligible_routes": ["Shiftr", "Paxus"],
        "research_status": "complete",
        "research_verified_fields": ["current_intent_research", "route_research"],
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_email": "taylor@example.com",
            "decision_maker_verification_status": "verified",
            "company_verification_evidence": ["https://example.com/company"],
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "remote engineering team",
            "observed_at": now,
            "evidence_url": "https://example.com/need",
        },
        "route_research": {
            "verified": True,
            "verification_status": "verified",
            "routes": {
                "Shiftr": {"verified": True, "verification_status": "verified", "evidence": "Acme needs a remote engineering team."},
                "Paxus": {"verified": True, "verification_status": "verified", "evidence": "Acme has a current technology staffing need."},
            },
        },
        "qualification_results": {
            "Shiftr": {"qualified": True},
            "Paxus": {"qualified": True, "true_referral": True},
        },
        "outreach_route": "Shiftr",
        "outreach_state": "awaiting_response",
        "outreach_attempt": 1,
        "outreach_history": [{"action_id": "a1"}],
        "conversation_id": f"conversation:{fingerprint}:shiftr",
    }


def test_inbound_response_is_durable_and_idempotent(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead()
    db.insert_if_new(lead)

    first = record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-1", text="Yes, I am interested", outcome="interested")
    second = record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-1", text="Yes, I am interested", outcome="interested")

    assert len(first["events"]) == 1
    assert len(second["events"]) == 1
    stored = db.get(lead["fingerprint"])
    assert stored["response_count"] == 1
    assert stored["revenue_lifecycle_state"] == "conversation_active"
    assert len(pending(db, "follow_up")) == 1
    assert pending(db, "follow_up")[0]["payload"]["authorized_by_role"] == "high_ticket_sales_closer"


def test_objection_follow_up_is_executed_by_closer_and_persisted(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("objection-test")
    db.insert_if_new(lead)
    transport = FakeTransport()
    register_revenue_transport(transport)
    try:
        record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-2", text="What does this cost?", outcome="objection", objection="What does this cost?")
        result = run_worker_once(db, "follow_up", worker_id="followup-worker")
        assert result["completed_count"] == 1
        assert result["failed_count"] == 0
        assert len(transport.calls) == 1
        stored = db.get(lead["fingerprint"])
        assert stored["revenue_lifecycle_state"] == "conversation_active"
        assert stored["outreach_state"] == "awaiting_response"
        assert stored["follow_up_due"] is True
        assert stored["next_follow_up_at"]
        assert len(stored["outreach_history"]) == 3
    finally:
        register_revenue_transport(None)


def test_opt_out_is_terminal_and_never_sends(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("optout-test")
    db.insert_if_new(lead)
    transport = FakeTransport()
    register_revenue_transport(transport)
    try:
        record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-3", text="Please stop contacting me", outcome="opted_out")
        assert pending(db, "follow_up") == []
        stored = db.get(lead["fingerprint"])
        assert stored["revenue_lifecycle_state"] == "closed_lost"
        assert stored["next_follow_up_at"] is None
        assert transport.calls == []
    finally:
        register_revenue_transport(None)


def test_conversation_can_switch_to_preserved_route(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("switch-test")
    db.insert_if_new(lead)
    record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=lead["conversation_id"], event_id="evt-4", text="We actually need a dedicated team", outcome="interested", suggested_route="Paxus")
    stored = db.get(lead["fingerprint"])
    assert stored["outreach_route"] == "Paxus"
    assert stored["route_switch_history"][0]["from"] == "Shiftr"
    assert stored["route_switch_history"][0]["to"] == "Paxus"
