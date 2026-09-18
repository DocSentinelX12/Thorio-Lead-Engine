from lead_engine.active_processing import _sales_eligibility
from lead_engine.database import LeadDB
from lead_engine.sales_handoff import package_digest


def _lead(qualified=True):
    return {
        "fingerprint": "sales-gate-test",
        "company": "Acme",
        "person": "Alex CTO",
        "business_need": "remote software engineer hiring",
        "qualified": qualified,
        "potential_routes": ["thorio"],
        "eligible_routes": ["thorio"],
        "preserved_routes": ["thorio"],
        "routing_result": {"destinations": ["thorio"], "review_required": False},
        "research_status: "complete",
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "remote software engineer hiring",
            "observed_at": "2026-09-14T00:00:00+00:00",
            "evidence_url": "https://example.com/need",
        },
        "company_research": {
            "company_verified": True,
            "decision_maker": "Alex CTO",
            "decision_maker_evidence": "company leadership page",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "alex@example.com",
        },
        "decision_maker_research": {"verified": True, "verification_status": "verified", "evidence": ["company leadership page"]},
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "remote software engineer hiring", "evidence": ["https://example.com/need"]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/hiring"]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/commercial"]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"thorio": {"verified": True, "verification_status": "verified", "evidence": "current need"}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": ["https://example.com/need"]},
    }


def _routing():
    return {"destinations": ["thorio"]}


def test_potential_routes_alone_cannot_enter_sales_execution():
    eligible, reason = _sales_eligibility(_lead(qualified=False), _routing(), {})
    assert eligible is False
    assert reason == "not_qualified"


def test_explicit_qualification_requires_confirmed_airtable_handoff(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead(qualified=True)
    db.insert_if_new(lead)
    eligible, reason = _sales_eligibility(lead, _routing(), {}, db)
    assert eligible is False
    assert reason == "airtable_handoff_required"


def test_exact_airtable_handoff_allows_sales_eligibility(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead(qualified=True)
    db.insert_if_new(lead)
    db.record_airtable_handoff(lead["fingerprint"], package_digest(lead), "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00")
    eligible, reason = _sales_eligibility(lead, _routing(), {}, db)
    assert eligible is True
    assert reason == "eligible"


def test_qualified_opportunity_survives_airtable_sync_failure():
    db = LeadDB(data_dir=tmp_path)
    lead = _lead(qualified=True)
    db.insert_if_new(lead)
    eligible, reason = _sales_eligibility(lead, _routing(), {"sync_error_present": True}, db)
    assert eligible is False
    assert reason == "airtable_handoff_required"
