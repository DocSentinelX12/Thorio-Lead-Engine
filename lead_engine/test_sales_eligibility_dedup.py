from datetime import datetime, timezone

from .active_processing import _sales_eligibility
from .database import LeadDB
from .sales_handoff import package_digest


def _lead(fingerprint, business_need="remote software engineer hiring"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": fingerprint,
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
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "verified company evidence",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "taylor@example.com",
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": business_need,
            "observed_at": now,
            "evidence_url": "https://example.com/need",
        },
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": business_need, "evidence": ["https://example.com/need"]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/hiring"]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/commercial"]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "current need"}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": ["https://example.com/need"]},
        "research_status": "complete",
    }


def _routing():
    return {"destinations": ["Thorio"], "review_required": False}


def test_missing_exact_opportunity_is_blocked(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("missing-opportunity", business_need="")
    db.insert_if_new(lead)
    eligible, reason = _sales_eligibility(lead, _routing(), {}, db)
    assert eligible is False
    assert reason == "missing_exact_opportunity"


def test_exact_same_company_person_and_need_is_blocked_as_duplicate(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    existing = _lead("existing-opportunity")
    current = _lead("current-opportunity")
    db.insert_if_new(existing)
    db.insert_if_new(current)
    db.record_airtable_handoff(current["fingerprint"], package_digest(current), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00")

    eligible, reason = _sales_eligibility(current, _routing(), {}, db)
    assert eligible is False
    assert reason == "exact_duplicate"


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
