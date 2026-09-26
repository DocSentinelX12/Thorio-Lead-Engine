from datetime import datetime, timezone
import threading
import pytest
from .active_processing import airtable_integrity
from .agent_queue import pending
from .agent_workers import run_worker_once
from .agent_queue import enqueue
from .database import LeadDB
from .revenue_execution import RevenueActionInProgress, RevenueAuthorizationError, execute_outbound, register_revenue_transport
from .sales_handoff import package_digest
from .research_intelligence import build_research_intelligence

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
    lead = {"fingerprint": fingerprint, "company": "Acme", "person": "Taylor", "contact_email": "taylor@example.com", "signal": "Acme is hiring a remote software engineer", "job_title": "Software Engineer", "business_need": "remote software engineer hiring", "need_at": now_text, "qualified": True, "potential_routes": ["Thorio", "Shiftr"], "eligible_routes": ["Thorio", "Shiftr"], "preserved_routes": ["Thorio", "Shiftr"], "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}, "research_status": "complete", "research_verified_fields": ["business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "contact_email": "taylor@example.com", "decision_maker_verification_status": "verified"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "evidence": [{"url": "https://example.com/need", "evidence": "Acme is actively hiring a remote software engineer.", "observed_at": now_text, "verification_status": "verified"}]}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/thorio", "evidence": "Acme has a current software engineering hiring need.", "observed_at": now_text, "verification_status": "verified"}]}, "Shiftr": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/shiftr", "evidence": "Acme has a current engineering need suitable for Shiftr.", "observed_at": now_text, "verification_status": "verified"}]}}}, "qualification_results": route_results, "evidence_events": [{"source_url": "https://example.com/signal", "signal": "Acme is hiring a remote software engineer"}], "decision_maker_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/taylor", "evidence": "Taylor is the verified decision-maker at Acme.", "observed_at": now_text, "verification_status": "verified"}]}, "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "remote software engineer hiring", "evidence": [{"url": "https://example.com/need", "evidence": "Acme needs a remote software engineer.", "observed_at": now_text, "verification_status": "verified"}]}, "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Acme has an open software engineering hiring need.", "observed_at": now_text, "verification_status": "verified"}]}, "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Acme has commercial software operations relevant to the opportunity.", "observed_at": now_text, "verification_status": "verified"}]}, "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/signal", "evidence": "Acme is hiring a remote software engineer.", "observed_at": now_text, "verification_status": "verified"}]}}
    lead["research_intelligence"] = build_research_intelligence(lead)
    return lead


def _confirm_handoff(db, lead):
    db.record_airtable_handoff(lead["fingerprint"], package_digest(lead), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00")

def test_sales_eligible_opportunity_is_handed_to_closer_without_manual_injection(tmp_path):
    db = LeadDB(data_dir=tmp_path); lead = _lead(); db.insert_if_new(lead); _confirm_handoff(db, lead); result = airtable_integrity("airtable_integrity", {"lead": lead, "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}}, type("Ctx", (), {"db": db})()); assert result["sales_eligibility"] == "eligible" and result["handoff"] == "outreach_closer"; queued = pending(db, "outreach_closer"); assert len(queued) == 1 and queued[0]["payload"]["lead"]["sales_eligibility"] == "eligible" and queued[0]["payload"]["lead"]["eligible_routes"] == ["Thorio", "Shiftr"]

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
    db = LeadDB(data_dir=tmp_path); lead = _lead("production-closer-test"); db.insert_if_new(lead); _confirm_handoff(db, lead); transport = FakeTransport(); register_revenue_transport(transport)
    try:
        airtable_integrity("airtable_integrity", {"lead": lead, "routing_result": {"destinations": ["Thorio", "Shiftr"], "review_required": False, "multi_route": True}}, type("Ctx", (), {"db": db})()); result = run_worker_once(db, "outreach_closer", worker_id="closer-worker"); assert result["completed_count"] == 1 and result["failed_count"] == 0 and len(transport.calls) == 1
        stored = db.get(lead["fingerprint"]); assert stored["revenue_lifecycle_state"] == "outreach_sent" and stored["outreach_state"] == "awaiting_response" and stored["outreach_history"] and stored["last_outreach_action_id"]
    finally: register_revenue_transport(None)


def test_closer_does_not_wait_for_airtable_handoff(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("nonblocking-airtable-test")
    lead["sales_eligibility"] = "eligible"
    db.insert_if_new(lead)
    enqueue(db, "outreach_closer", {"lead": lead}, priority=10, dedupe_key="sales:nonblocking-airtable-test")
    transport = FakeTransport()
    register_revenue_transport(transport)
    try:
        result = run_worker_once(db, "outreach_closer", worker_id="closer-worker")
        assert result["completed_count"] == 1
        assert result["failed_count"] == 0
        assert len(transport.calls) == 1
    finally:
        register_revenue_transport(None)


def test_existing_inflight_idempotency_claim_blocks_duplicate_send(tmp_path):
    key = "outreach:concurrent:conversation-1:1"
    db = LeadDB(data_dir=tmp_path)
    claim = db.claim_revenue_action(
        key,
        {
            "action_id": "claimed-action",
            "opportunity_id": "concurrent",
            "conversation_id": "conversation-1",
            "idempotency_key": key,
            "channel": "email",
            "status": "sending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert claim is None
    db.close()

    class NoReconcileTransport:
        def __init__(self):
            self.calls = 0

        def send(self, **kwargs):
            self.calls += 1
            return {"provider": "fake", "delivery_id": "duplicate", "status": "accepted"}

        def reconcile(self, *, idempotency_key):
            return None

    db = LeadDB(data_dir=tmp_path)
    transport = NoReconcileTransport()
    try:
        with pytest.raises(RevenueActionInProgress):
            execute_outbound(
                db,
                worker_capability="high_ticket_sales_closer",
                opportunity_id="concurrent",
                conversation_id="conversation-1",
                channel="email",
                recipient={"email": "taylor@example.com"},
                subject="Hello",
                body="Hello Taylor",
                transport=transport,
                idempotency_key=key,
            )
        assert transport.calls == 0
        assert db.get_state("revenue_execution")["actions"][key]["action_id"] == "claimed-action"
    finally:
        db.close()

def test_uncertain_send_without_provider_reconciliation_never_resends(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    key = "outreach:uncertain:conversation-1:1"

    class UnknownTransport:
        def __init__(self):
            self.calls = 0

        def send(self, **kwargs):
            self.calls += 1
            raise RuntimeError("connection lost after possible provider acceptance")

        def reconcile(self, *, idempotency_key):
            return None

    transport = UnknownTransport()
    with pytest.raises(RuntimeError):
        execute_outbound(
            db,
            worker_capability="high_ticket_sales_closer",
            opportunity_id="uncertain",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
            idempotency_key=key,
        )

    with pytest.raises(RevenueActionInProgress):
        execute_outbound(
            db,
            worker_capability="high_ticket_sales_closer",
            opportunity_id="uncertain",
            conversation_id="conversation-1",
            channel="email",
            recipient={"email": "taylor@example.com"},
            subject="Hello",
            body="Hello Taylor",
            transport=transport,
            idempotency_key=key,
        )

    assert transport.calls == 1
