from datetime import datetime, timezone

import pytest

from .active_processing import airtable_integrity
from .agent_queue import pending
from .agent_workers import run_worker_once
from .database import LeadDB
from .revenue_execution import RevenueAuthorizationError, execute_outbound, register_revenue_transport


class FakeTransport:
    def __init__(self):
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}


def _lead(fingerprint="revenue-lifecycle-test"):
    return {
        "fingerprint": fingerprint,
        "company": "Acme",
        "person": "Taylor",
        "contact_email": "taylor@example.com",
        "signal": "Acme is hiring a remote software engineer",
        "job_title": "Software Engineer",
        "need_at": datetime.now(timezone.utc).isoformat(),
        "qualified": True,
        "potential_routes": ["Thorio", "Shiftr"],
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "contact_email": "taylor@example.com",
            "decision_maker_verification_status": "verified",
        },
        "qualification_results": {
            "Thorio": {"qualified": True},
            "Shiftr": {"qualified": True},
        },
        "evidence_events": [
            {"source_url": "https://example.com/signal", "signal": "Acme is hiring a remote software engineer"}
        ],
    }


def test_sales_eligible_opportunity_is_handed_to_closer_without_manual_injection(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead()
    db.insert_if_new(lead)

    result = airtable_integrity(
        "airtable_integrity",
        {
            "lead": lead,
            "routing_result": {
                "destinations": ["Thorio", "Shiftr"],
                "review_required": False,
                "multi_route": True,
            },
        },
        type("Ctx", (), {"db": db})(),
    )

    assert result["sales_eligibility"] == "eligible"
    assert result["handoff"] == "outreach_closer"
    queued = pending(db, "outreach_closer")
    assert len(queued) == 1
    assert queued[0]["payload"]["lead"]["sales_eligibility"] == "eligible"
    assert queued[0]["payload"]["lead"]["eligible_routes"] == ["Thorio", "Shiftr"]


def test_general_capability_cannot_send_outbound(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    transport = FakeTransport()
    with pytest.raises(RevenueAuthorizationError):
        execute_outbound(
            db,
            worker_capability="researcher",
            opportunity_id="opportunity-1",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
        )
    assert transport.calls == []


def test_privileged_closer_sends_once_and_persists_delivery(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    transport = FakeTransport()
    register_revenue_transport(transport)
    try:
        result = execute_outbound(
            db,
            worker_capability="high_ticket_sales_closer",
            opportunity_id="opportunity-1",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
            idempotency_key="outreach:opportunity-1:conversation-1:1",
        )
        replay = execute_outbound(
            db,
            worker_capability="high_ticket_sales_closer",
            opportunity_id="opportunity-1",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
            idempotency_key="outreach:opportunity-1:conversation-1:1",
        )
        assert result.status == "sent"
        assert replay.action_id == result.action_id
        assert len(transport.calls) == 1
        state = db.get_state("revenue_execution")
        assert state["actions"]["outreach:opportunity-1:conversation-1:1"]["status"] == "sent"
    finally:
        register_revenue_transport(None)


def test_production_closer_sends_and_marks_outreach_sent(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("production-closer-test")
    db.insert_if_new(lead)
    transport = FakeTransport()
    register_revenue_transport(transport)
    try:
        airtable_integrity(
            "airtable_integrity",
            {"lead": lead, "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}},
            type("Ctx", (), {"db": db})(),
        )
        result = run_worker_once(db, "outreach_closer", worker_id="closer-worker")
        assert result["completed_count"] == 1
        assert result["failed_count"] == 0
        assert len(transport.calls) == 1
        stored = db.get(lead["fingerprint"])
        assert stored["revenue_lifecycle_state"] == "outreach_sent"
        assert stored["outreach_state"] == "awaiting_response"
        assert stored["outreach_history"]
        assert stored["last_outreach_action_id"]
    finally:
        register_revenue_transport(None)
