from datetime import datetime, timezone
from .agent_registry import agent_registry
from .agent_specializations import specialization_registry
from .agent_queue import enqueue
from .agent_workers import run_worker_once
from .browser_revenue_transport import BrowserRevenueUnavailable
from .database import LeadDB
from .revenue_execution import register_revenue_transport, RevenueTransportUnavailable

class _BrowserUnavailableTransport:
    def send(self, **kwargs): raise BrowserRevenueUnavailable("browser session unavailable")
    def reconcile(self, *, idempotency_key): return None

def _lead(fingerprint="browser-retry-boundary"):
    now = datetime.now(timezone.utc).isoformat()
    return {"fingerprint": fingerprint, "company": "Acme", "qualified": True, "sales_eligibility": "eligible", "potential_routes": ["Thorio"], "signal": "Acme is hiring a remote software engineer", "research_status": "complete", "research_verified_fields": ["current_intent_research", "route_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "contact_email": "taylor@example.com", "decision_maker_verification_status": "verified"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence_url": "https://example.com/need"}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Acme has a current software engineering hiring need."}}}, "qualification_results": {"Thorio": {"qualified": True, "route_research": {"verified": True, "evidence": "Acme has a current software engineering hiring need."}}}, "evidence_events": [{"source_url": "https://example.com/signal"}], "need_at": now}

def test_browser_unavailable_is_a_retryable_revenue_transport_failure(tmp_path):
    assert issubclass(BrowserRevenueUnavailable, RevenueTransportUnavailable)
    db = LeadDB(data_dir=tmp_path); lead = _lead(); db.insert_if_new(lead); enqueue(db, "outreach_closer", {"lead": lead}); register_revenue_transport(_BrowserUnavailableTransport())
    try: result = run_worker_once(db, "outreach_closer", worker_id="browser-retry-worker")
    finally: register_revenue_transport(None)
    assert result["completed_count"] == 0 and result["failed_count"] == 0 and result["retryable_count"] == 1

def test_outreach_closer_metadata_declares_authorized_execution():
    role = agent_registry()["outreach_closer"]; specialization = specialization_registry()["outreach_closer"]; assert "execute" in role.purpose.lower(); assert "authorize" in specialization.mission.lower(); assert "execute authorized outbound" in {item.lower() for item in specialization.responsibilities}
