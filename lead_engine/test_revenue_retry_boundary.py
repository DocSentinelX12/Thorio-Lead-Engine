from datetime import datetime, timezone
from .agent_registry import agent_registry
from .agent_specializations import specialization_registry
from .agent_queue import enqueue
from .agent_workers import run_worker_once
from .browser_revenue_transport import BrowserRevenueUnavailable
from .database import LeadDB
from .revenue_execution import register_revenue_transport, RevenueTransportUnavailable
from .research_intelligence import build_research_intelligence
from .sales_handoff import package_digest

class _BrowserUnavailableTransport:
    def send(self, **kwargs): raise BrowserRevenueUnavailable("browser session unavailable")
    def reconcile(self, *, idempotency_key): return None

def _lead(fingerprint="browser-retry-boundary"):
    now = datetime.now(timezone.utc).isoformat()
    lead = {"fingerprint": fingerprint, "opportunity_id": fingerprint, "company": "Acme", "person": "Taylor", "contact_email": "taylor@example.com", "qualified": True, "sales_eligibility": "eligible", "potential_routes": ["Thorio"], "eligible_routes": ["Thorio"], "preserved_routes": ["Thorio"], "routing_result": {"destinations": ["Thorio"], "review_required": False}, "signal": "Acme is hiring a remote software engineer", "business_need": "remote software engineer hiring", "research_status": "complete", "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "contact_email": "taylor@example.com", "decision_maker_verification_status": "verified", "public_company_facts": [{"url": "https://example.com/company", "evidence": "Acme company profile", "observed_at": now, "verification_status": "verified"}]}, "decision_maker_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/taylor", "evidence": "Taylor is the decision maker", "observed_at": now, "verification_status": "verified"}]}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence": [{"url": "https://example.com/need", "evidence": "Current engineering hiring intent", "observed_at": now, "verification_status": "verified"}]}, "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Acme has a current software engineering hiring need", "observed_at": now, "verification_status": "verified"}]}}}, "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "remote software engineer hiring", "evidence": [{"url": "https://example.com/need", "evidence": "Acme needs a remote software engineer", "observed_at": now, "verification_status": "verified"}]}, "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Acme is hiring software engineers", "observed_at": now, "verification_status": "verified"}]}, "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Commercial context", "observed_at": now, "verification_status": "verified"}]}, "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Current engineering need", "observed_at": now, "verification_status": "verified"}]}}
    lead["research_intelligence"] = build_research_intelligence(lead)
    return lead

def test_browser_unavailable_is_a_retryable_revenue_transport_failure(tmp_path):
    assert issubclass(BrowserRevenueUnavailable, RevenueTransportUnavailable)
    db = LeadDB(data_dir=tmp_path); lead = _lead(); db.insert_if_new(lead); db.record_airtable_handoff(lead["fingerprint"], package_digest(lead), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00"); enqueue(db, "outreach_closer", {"lead": lead}); register_revenue_transport(_BrowserUnavailableTransport())
    try: result = run_worker_once(db, "outreach_closer", worker_id="browser-retry-worker")
    finally: register_revenue_transport(None)
    assert result["completed_count"] == 0 and result["failed_count"] == 0 and result["retryable_count"] == 1, result

def test_outreach_closer_metadata_declares_authorized_execution():
    role = agent_registry()["outreach_closer"]; specialization = specialization_registry()["outreach_closer"]; assert "execute" in role.purpose.lower(); assert "authorize" in specialization.mission.lower(); assert "execute authorized outbound" in {item.lower() for item in specialization.responsibilities}
