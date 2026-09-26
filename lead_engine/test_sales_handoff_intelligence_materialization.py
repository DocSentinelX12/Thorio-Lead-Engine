from datetime import datetime, timezone

from .sales_handoff import package_is_ready, package_projection


def _complete_lead() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": "handoff-materialization-test",
        "opportunity_id": "handoff-materialization-test",
        "company": "Acme",
        "person": "Taylor",
        "contact_email": "taylor@example.com",
        "business_need": "remote software engineer hiring",
        "qualified": True,
        "qualification_status": "qualified",
        "potential_routes": ["Thorio"],
        "eligible_routes": ["Thorio"],
        "preserved_routes": ["Thorio"],
        "routing_result": {"destinations": ["Thorio"], "review_required": False},
        "research_status": "complete",
        "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_verification_status": "verified", "decision_maker_email": "taylor@example.com"},
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "remote software engineer hiring", "evidence": [{"url": "https://example.com/need", "evidence": "Current hiring need", "observed_at": now}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "remote software engineer hiring", "observed_at": now, "evidence": [{"url": "https://example.com/intent", "evidence": "Current intent", "observed_at": now}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Software engineering hiring", "observed_at": now}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Commercial context", "observed_at": now}]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Current remote engineering need", "observed_at": now}]}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Current hiring need", "observed_at": now}]},
    }


def test_complete_canonical_research_materializes_intelligence_at_handoff_boundary():
    lead = _complete_lead()
    assert "research_intelligence" not in lead
    projection = package_projection(lead)
    intelligence = projection["research_intelligence"]
    assert intelligence["opportunity_id"] == lead["opportunity_id"]
    assert intelligence["claims"]
    assert intelligence["evidence_graph"]["nodes"]
    assert intelligence["handoff"]["ready"] is True
    assert package_is_ready(lead) is True


def test_empty_intelligence_still_fails_when_canonical_research_is_incomplete():
    lead = _complete_lead()
    lead["commercial_research"] = {"verified": True, "verification_status": "verified", "evidence": []}
    lead["research_status"] = "complete"
    assert package_is_ready(lead) is False
