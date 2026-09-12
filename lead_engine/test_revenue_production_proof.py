from datetime import datetime, timezone

from .agent_orchestrator import AgentOrchestrator
from .agent_queue import pending
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


def _lead():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": "production-revenue-proof",
        "company": "Acme",
        "person": "Taylor CTO",
        "contact_email": "taylor@example.com",
        "signal": "Acme is hiring a remote software engineer",
        "evidence": "Acme is hiring a remote software engineer",
        "source": "LinkedIn",
        "source_url": "https://example.com/post",
        "url": "https://example.com/post",
        "observed_at": now,
        "need_at": now,
        "business_need": "remote software engineer hiring",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor CTO",
            "decision_maker_evidence": "https://example.com/company/team",
            "decision_maker_email": "taylor@example.com",
            "decision_maker_title": "Chief Technology Officer",
            "decision_maker_verification_status": "verified",
            "fabricated_fields": [],
        },
    }


def _drain(orchestrator, rounds=30):
    return orchestrator.run_all_once(limit_per_agent=1, max_rounds=rounds)


def _proof_debug(db, stored, first):
    return {
        "lead": {key: stored.get(key) for key in ("qualified", "potential_routes", "qualification_results", "research_status", "company_research", "sales_eligibility", "sales_eligibility_reason", "revenue_lifecycle_state", "route", "eligible_routes")},
        "pending": [(task.get("agent"), task.get("status"), task.get("error"), task.get("payload", {}).get("lead", {}).get("fingerprint")) for task in pending(db)],
        "drain": first,
    }


def test_complete_production_revenue_lifecycle_has_no_orphaned_qualified_opportunity(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_AGENT_EXECUTION_WORKERS", "1")
    db = LeadDB(data_dir=tmp_path)
    lead = _lead()
    assert db.insert_if_new(lead) is True
    transport = FakeTransport()
    register_revenue_transport(transport)
    try:
        orchestrator = AgentOrchestrator(db, worker_prefix="production-proof")
        orchestrator.dispatch_discovery("linkedin_signal", lead, priority=10)
        first = _drain(orchestrator)
        stored = db.get(lead["fingerprint"])
        assert stored is not None
        assert stored["qualified"] is True
        assert stored.get("sales_eligibility") == "eligible", _proof_debug(db, stored, first)
        assert stored["revenue_lifecycle_state"] == "outreach_sent"
        assert stored["outreach_state"] == "awaiting_response"
        assert len(transport.calls) == 1
        assert not any(task.get("agent") == "outreach_closer" and task.get("status") == "queued" for task in pending(db))
        assert first["failed_count"] == 0

        record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=stored["conversation_id"], event_id="response-1", text="Yes, let's talk", outcome="interested")
        second = _drain(orchestrator)
        stored = db.get(lead["fingerprint"])
        assert second["failed_count"] == 0
        assert len(transport.calls) == 2
        assert stored["revenue_lifecycle_state"] == "conversation_active"
        assert stored["outreach_state"] == "awaiting_response"
        assert stored["follow_up_due"] is True
        assert stored["next_follow_up_at"]

        orphaned = []
        for candidate in db.all_leads():
            if candidate.get("qualified") is not True:
                continue
            if candidate.get("sales_eligibility") == "eligible" and not candidate.get("conversation_id"):
                orphaned.append(candidate["fingerprint"])
        assert orphaned == []
    finally:
        register_revenue_transport(None)
        db.close()
