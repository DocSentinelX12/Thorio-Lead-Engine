from datetime import datetime, timezone
import pytest
from .active_processing import airtable_integrity
from .agent_queue import pending
from .agent_workers import run_worker_once
from .database import LeadDB
from .revenue_execution import RevenueActionInProgress, RevenueAuthorizationError, execute_outbound, register_revenue_transport

class FakeTransport:
    def __init__(self): self.calls = []
    def send(self, **kwargs): self.calls.append(dict(kwargs)); return {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}
    def reconcile(self, *, idempotency_key): return None
class CrashAfterAcceptanceTransport(FakeTransport):
    def __init__(self): super().__init__(); self.accepted = {}; self.crash_once = True
    def send(self, **kwargs):
        self.calls.append(dict(kwargs)); result = {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}; self.accepted[kwargs["idempotency_key"]] = result
        if self.crash_once: self.crash_once = False; raise RuntimeError("connection lost after provider acceptance")
        return result
    def reconcile(self, *, idempotency_key): return self.accepted.get(idempotency_key)

def _lead(fingerprint="revenue-lifecycle-test"):
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    route_results = {"Thorio": {"qualified": True, "route_research": {"verified": True, "evidence": "Acme has a current software engineering hiring need."}}, "Shiftr": {"qualified": True, "route_research": {"verified": True, "evidence": "Acme has a current engineering need suitable for Shiftr."}}}
    return {"fingerprint": fingerprint, "company": "Acme", "person": "Taylor", "contact_email": "taylor@example.com", "signal": "Acme is hiring a remote software engineer", "job_title": "Software Engineer", "business_need": "remote software engineer hiring", "need_at": now_text, "qualified": True, "potential_routes": ["Thorio", "Shiftr"], "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "contact_email": "taylor@example.com", "decision_maker_verification_status": "verified"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now_text, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Acme has a current software engineering hiring need."}, "Shiftr": {"verified": True, "verification_status": "verified", "evidence": "Acme has a current engineering need suitable for Shiftr."}}}, "qualification_results": route_results, "evidence_events": [{"source_url": "https://example.com/signal", "signal": "Acme is hiring a remote software engineer"}]}

def test_sales_eligible_opportunity_is_handed_to_closer_without_manual_injection(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead(); db.insert_if_new(lead); result = airtable_integrity("airtable_integrity", {"lead": lead, "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}}, type("Ctx", (), {"db": db})()); assert result["sales_eligibility"] == "eligible" and result["handoff"] == "outreach_closer"; queued = pending(db, "outreach_closer"); assert len(queued) == 1 and queued[0]["payload"]["lead"]["sales_eligibility"] == "eligible" and queued[0]["payload"]["lead"]["eligible_routes"] == ["Thorio", "Shiftr"]

def test_general_capability_cannot_send_outbound(tmp_path):
    db = LeadDB(data_dir=tmp_path); transport = FakeTransport()
    with pytest.raises(RevenueAuthorizationError): execute_outbound(db, worker_capability="researcher", opportunity_id="opportunity-1", conversation_id="conversation-1", channel="email", recipient={"email": "taylor@example.com"}, subject="Hello", body="Hello Taylor", transport=transport)
    assert transport.calls == []

def test_privileged_closer_sends_once_and_persists_delivery(tmp_path):
    db = LeadDB(data_dir=tmp_path); transport = FakeTransport(); register_revenue_transport(transport)
    try:
        result = execute_outbound(db, worker_capability="high_ticket_sales_closer", opportunity_id="opportunity-1", conversation_id="conversation-1", channel="email", recipient={"email": "taylor@example.com"}, subject="Hello", body="Hello Taylor", transport=transport, idempotency_key="outreach:opportunity-1:conversation-1:1"); replay = execute_outbound(db, worker_capability="high_ticket_sales_closer", opportunity_id="opportunity-1", conversation_id="conversation-1", channel="email", recipient={"email": "taylor@example.com"}, subject="Hello", body="Hello Taylor", transport=transport, idempotency_key="outreach:opportunity-1:conversation-1:1")
        assert result.status == "sent" and replay.action_id == result.action_id and len(transport.calls) == 1 and db.get_state("revenue_execution")["actions"]["outreach:opportunity-1:conversation-1:1"]["status"] == "sent"
    finally: register_revenue_transport(None)

def test_provider_acceptance_is_reconciled_without_duplicate_send(tmp_path):
    db = LeadDB(data_dir=tmp_path); transport = CrashAfterAcceptanceTransport(); key = "outreach:crash-safe:conversation-1:1"
    with pytest.raises(RuntimeError): execute_outbound(db, worker_capability="high_ticket_sales_closer", opportunity_id="crash-safe", conversation_id="conversation-1", channel="email", recipient={"email": "taylor@example.com"}, subject="Hello", body="Hello Taylor", transport=transport, idempotency_key=key)
    result = execute_outbound(db, worker_capability="high_ticket_sales_closer", opportunity_id="crash-safe", conversation_id="conversation-1", channel="email", recipient={"email": "taylor@example.com"}, subject="Hello", body="Hello Taylor", transport=transport, idempotency_key=key); assert result.status == "sent" and len(transport.calls) == 1 and db.get_state("revenue_execution")["actions"][key]["status"] == "sent"

def test_production_closer_sends_and_marks_outreach_sent(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead("production-closer-test"); db.insert_if_new(lead); transport = FakeTransport(); register_revenue_transport(transport)
    try:
        airtable_integrity("airtable_integrity", {"lead": lead, "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}}, type("Ctx", (), {"db": db})()); result = run_worker_once(db, "outreach_closer", worker_id="closer-worker"); assert result["completed_count"] == 1 and result["failed_count"] == 0 and len(transport.calls) == 1
        stored = db.get(lead["fingerprint"]); assert stored["revenue_lifecycle_state"] == "outreach_sent" and stored["outreach_state"] == "awaiting_response" and stored["outreach_history"] and stored["last_outreach_action_id"]
    finally: register_revenue_transport(None)


class ProcessDeathAfterAcceptanceTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.accepted = {}

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        result = {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}
        self.accepted[kwargs["idempotency_key"]] = result
        raise SystemExit("simulated worker death after provider acceptance")

    def reconcile(self, *, idempotency_key):
        return self.accepted.get(idempotency_key)


def test_worker_death_after_provider_acceptance_recovers_without_resend(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    transport = ProcessDeathAfterAcceptanceTransport()
    key = "outreach:process-death:conversation-1:1"

    with pytest.raises(SystemExit):
        execute_outbound(
            db,
            worker_capability="high_ticket_sales_closer",
            opportunity_id="process-death",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
            idempotency_key=key,
        )

    assert db.get_state("revenue_execution")["actions"][key]["status"] == "sending"
    transport_result = transport.reconcile(idempotency_key=key)
    assert transport_result is not None

    result = execute_outbound(
        db,
        worker_capability="high_ticket_sales_closer",
        opportunity_id="process-death",
        conversation_id="conversation-1",
        channel="email",
        recipient={"email": "taylor@example.com"},
        subject="Hello",
        body="Hello Taylor",
        transport=transport,
        idempotency_key=key,
    )
    assert result.status == "sent"
    assert len(transport.calls) == 1
    assert db.get_state("revenue_execution")["actions"][key]["status"] == "sent"


def test_unresolved_inflight_action_cannot_be_sent_again(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    transport = FakeTransport()
    key = "outreach:inflight:conversation-1:1"
    db.set_state(
        "revenue_execution",
        {
            "actions": {
                key: {
                    "action_id": "claimed-action",
                    "opportunity_id": "inflight",
                    "conversation_id": "conversation-1",
                    "idempotency_key": key,
                    "channel": "email",
                    "status": "sending",
                }
            }
        },
    )

    with pytest.raises(RevenueActionInProgress):
        execute_outbound(
            db,
            worker_capability="high_ticket_sales_closer",
            opportunity_id="inflight",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
            idempotency_key=key,
        )
    assert transport.calls == []


def test_closer_reconciles_sent_provider_action_into_lead_after_worker_death(tmp_path):
    from .agent_workers import _outreach_closer, AgentExecutionContext
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("closer-recovery-test")
    db.insert_if_new(lead)
    transport = ProcessDeathAfterAcceptanceTransport()
    ctx = AgentExecutionContext(db=db, worker_id="closer-worker", revenue_transport=transport)

    with pytest.raises(SystemExit):
        _outreach_closer("outreach_closer", {"lead": lead}, ctx)

    stale = db.get(lead["fingerprint"])
    assert not stale.get("last_outreach_action_id")
    result = _outreach_closer("outreach_closer", {"lead": stale}, ctx)

    assert result["action"] == "send_outreach"
    assert len(transport.calls) == 1
    stored = db.get(lead["fingerprint"])
    assert stored["last_outreach_action_id"]
    assert stored["outreach_attempt"] == 1
    assert len(stored["outreach_history"]) == 1
    assert stored["outreach_state"] == "awaiting_response"


def test_follow_up_reconciles_sent_provider_action_into_lead_after_worker_death(tmp_path):
    from .agent_workers import _follow_up, AgentExecutionContext
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("followup-recovery-test")
    lead.update({
        "conversation_id": "conversation:followup-recovery-test:Thorio",
        "outreach_route": "Thorio",
        "outreach_state": "awaiting_response",
        "outreach_attempt": 1,
        "outreach_history": [{"action_id": "prior-action", "conversation_id": "conversation:followup-recovery-test:Thorio", "route": "Thorio", "channel": "email", "status": "sent"}],
        "last_outreach_action_id": "prior-action",
    })
    db.insert_if_new(lead)
    transport = ProcessDeathAfterAcceptanceTransport()
    ctx = AgentExecutionContext(db=db, worker_id="followup-worker", revenue_transport=transport)
    payload = {"lead": lead, "outcome": "interested", "execute": True}

    with pytest.raises(SystemExit):
        _follow_up("follow_up", payload, ctx)

    stale = db.get(lead["fingerprint"])
    result = _follow_up("follow_up", {"lead": stale, "outcome": "interested", "execute": True}, ctx)

    assert result["action"] == "send_follow_up"
    assert len(transport.calls) == 1
    stored = db.get(lead["fingerprint"])
    assert stored["last_outreach_action_id"]
    assert stored["outreach_attempt"] == 2
    assert len(stored["outreach_history"]) == 2
    assert stored["outreach_state"] == "awaiting_response"
