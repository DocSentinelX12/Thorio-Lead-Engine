from datetime import datetime, timezone
from .agent_orchestrator import AgentOrchestrator
from .agent_queue import pending
from .database import LeadDB
from .revenue_conversation import record_inbound_event
from .revenue_execution import register_revenue_transport
from . import advanced_agent_logic

class FakeTransport:
    def __init__(self): self.calls = []
    def send(self, **kwargs): self.calls.append(dict(kwargs)); return {"provider": "fake", "delivery_id": f"delivery-{len(self.calls)}", "status": "accepted"}
    def reconcile(self, *, idempotency_key): return None

def _lead():
    now = datetime.now(timezone.utc).isoformat()
    return {"fingerprint": "production-revenue-proof", "company": "Acme", "person": "Taylor CTO", "contact_email": "taylor@example.com", "signal": "Acme is hiring a remote software engineer", "evidence": "Acme is hiring a remote software engineer", "source": "LinkedIn", "source_url": "https://example.com/post", "url": "https://example.com/post", "observed_at": now, "need_at": now, "business_need": "remote software engineer hiring", "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Current remote software engineering hiring need."}}}, "company_research": {"company_verified": True, "decision_maker": "Taylor CTO", "decision_maker_evidence": "https://example.com/company/team", "decision_maker_email": "taylor@example.com", "decision_maker_title": "Chief Technology Officer", "decision_maker_verification_status": "verified", "fabricated_fields": []}}

def _drain(orchestrator, rounds=30): return orchestrator.run_all_once(limit_per_agent=1, max_rounds=rounds)
def _proof_debug(db, stored, drain, transport): return {"sales_eligibility": stored.get("sales_eligibility"), "revenue_lifecycle_state": stored.get("revenue_lifecycle_state"), "outreach_state": stored.get("outreach_state"), "outreach_attempt": stored.get("outreach_attempt"), "last_action": stored.get("last_outreach_action_id"), "pending_agents": sorted({task.get("agent") for task in pending(db) if task.get("status") in {"queued", "running"}}), "calls": [{"subject": call.get("subject"), "body": call.get("body"), "idempotency_key": call.get("idempotency_key")} for call in transport.calls], "drain": drain}

def test_complete_production_revenue_lifecycle_has_no_orphaned_qualified_opportunity(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_AGENT_EXECUTION_WORKERS", "1")
    monkeypatch.setattr(advanced_agent_logic, "research_public_web", lambda value: {"status": "evidence_found", "researched_at": "2026-09-14T00:00:00+00:00", "pages_attempted": 1, "pages_collected": 1, "sources": [{"url": "https://acme.example/", "observed_at": "2026-09-14T00:00:00+00:00", "status": "collected"}], "facts": {"company": [{"url": "https://acme.example/", "evidence": "Acme public company page"}], "hiring": [], "product": [], "decision_maker": [], "business_need": [], "commercial": []}, "raw_pages": [{"url": "https://acme.example/", "status": "collected", "facts": [{"field": "page_text", "value": "Acme public company page", "evidence_url": "https://acme.example/"}]}], "fabricated_fields": []})
    db = LeadDB(data_dir=tmp_path); lead = _lead(); assert db.insert_if_new(lead) is True; transport = FakeTransport(); register_revenue_transport(transport)
    try:
        orchestrator = AgentOrchestrator(db, worker_prefix="production-proof"); orchestrator.dispatch_discovery("linkedin_signal", lead, priority=10); first = _drain(orchestrator); stored = db.get(lead["fingerprint"]); assert stored is not None; assert first["failed_count"] == 0, first; assert stored["qualified"] is True; assert stored.get("sales_eligibility") == "eligible", _proof_debug(db, stored, first, transport); assert stored["revenue_lifecycle_state"] == "outreach_sent", _proof_debug(db, stored, first, transport); assert stored["outreach_state"] == "awaiting_response"; assert len(transport.calls) == 1; assert not any(task.get("agent") == "outreach_closer" and task.get("status") == "queued" for task in pending(db))
        record_inbound_event(db, opportunity_id=lead["fingerprint"], conversation_id=stored["conversation_id"], event_id="response-1", text="Yes, let's talk", outcome="interested"); second = _drain(orchestrator); stored = db.get(lead["fingerprint"]); assert second["failed_count"] == 0, second; assert len(transport.calls) == 2; assert "following up" in str(transport.calls[1].get("body", "")).lower(), _proof_debug(db, stored, second, transport); assert stored["revenue_lifecycle_state"] == "conversation_active" and stored["outreach_state"] == "awaiting_response" and stored["follow_up_due"] is True and stored["next_follow_up_at"]
        orphaned = [candidate["fingerprint"] for candidate in db.all_leads() if candidate.get("qualified") is True and candidate.get("sales_eligibility") == "eligible" and not candidate.get("conversation_id")]; assert orphaned == []
    finally: register_revenue_transport(None); db.close()
