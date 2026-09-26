from datetime import datetime, timezone

from .active_processing import _sales_eligibility
from .database import LeadDB
from .research_intelligence import build_research_intelligence
from .sales_handoff import package_digest


def _lead(fingerprint, business_need="remote software engineer hiring"):
    now = datetime.now(timezone.utc).isoformat()
    lead = {
        "fingerprint": fingerprint,
        "opportunity_id": fingerprint,
        "company": "Acme",
        "person": "Taylor",
        "business_need": business_need,
        "contact_email": "taylor@example.com",
        "qualified": True,
        "potential_routes": ["Thorio"],
        "eligible_routes": ["Thorio"],
        "preserved_routes": ["Thorio"],
        "routing_result": {"destinations": ["Thorio"], "review_required": False},
        "need_at": now,
        "research_status": "complete",
        "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_verification_status": "verified", "decision_maker_email": "taylor@example.com", "public_company_facts": [{"url": "https://example.com/company", "evidence": "Acme company profile", "observed_at": now, "verification_status": "verified"}]},
        "decision_maker_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/taylor", "evidence": "Taylor is the decision maker", "observed_at": now, "verification_status": "verified"}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": business_need, "observed_at": now, "evidence": [{"url": "https://example.com/intent", "evidence": business_need, "observed_at": now, "verification_status": "verified"}]},
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": business_need, "evidence": [{"url": "https://example.com/need", "evidence": business_need, "observed_at": now, "verification_status": "verified"}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Technical hiring need", "observed_at": now, "verification_status": "verified"}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Commercial context", "observed_at": now, "verification_status": "verified"}]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Current need", "observed_at": now, "verification_status": "verified"}]}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": business_need, "observed_at": now, "verification_status": "verified"}]},
    }
    lead["research_intelligence"] = build_research_intelligence(lead)
    return lead


def _routing():
    return {"destinations": ["Thorio"], "review_required": False}


def test_missing_exact_opportunity_is_blocked(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("missing-opportunity", business_need="")
    db.insert_if_new(lead)
    eligible, reason = _sales_eligibility(lead, _routing(), {}, db)
    assert eligible is False
    assert reason == "missing_exact_opportunity"


def test_exact_same_company_person_and_need_is_not_blocked_after_verification(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    existing = _lead("existing-opportunity")
    current = _lead("current-opportunity")
    db.insert_if_new(existing)
    db.insert_if_new(current)
    db.record_airtable_handoff(current["fingerprint"], package_digest(current), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00")
    eligible, reason = _sales_eligibility(current, _routing(), {}, db)
    assert eligible is True
    assert reason == "eligible"


def test_different_business_need_remains_eligible(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    existing = _lead("existing-opportunity")
    current = _lead("current-opportunity", business_need="AI agent development")
    db.insert_if_new(existing)
    db.insert_if_new(current)
    db.record_airtable_handoff(current["fingerprint"], package_digest(current), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00")
    eligible, reason = _sales_eligibility(current, _routing(), {}, db)
    assert eligible is True
    assert reason == "eligible"
