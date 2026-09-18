from datetime import datetime, timezone

from .agent_stateful_handlers import verification
from .qualification import apply_company_qualification


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _primary_lead():
    now = _timestamp()
    return {
        "fingerprint": "qualification-b-test",
        "company": "Acme",
        "person": "Alex CTO",
        "signal": "Acme is hiring a remote software engineer",
        "evidence": "Acme is hiring a remote software engineer",
        "observed_at": now,
        "research_status": "complete",
        "company_research": {"company_verified": True, "decision_maker": "Alex CTO", "decision_maker_evidence": "Alex CTO was named in the source evidence.", "decision_maker_verification_status": "verified", "decision_maker_email": "alex@example.com"},
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "Acme is hiring a remote software engineer", "observed_at": now},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "Acme is hiring a remote software engineer", "observed_at": now},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "Acme has a current remote software engineering hiring need suitable for Thorio."}, "Shiftr": {"verified": False, "evidence": ""}, "Paxus": {"verified": False, "evidence": ""}}},
        "potential_routes": ["Thorio"],
        "qualification_results": {"Thorio": {"qualified": True, "category_score": 1, "matched_category": True, "current_need": {"qualified": True, "observed_at": now, "evidence": "Acme is hiring a remote software engineer"}, "recent_inquiry": {"qualified": False, "observed_at": None}, "route_research": {"verified": True, "evidence": "Acme has a current remote software engineering hiring need suitable for Thorio."}}},
        "qualification_review_stage": "primary",
    }


def test_qualification_b_is_independent_and_preserves_valid_route():
    result = apply_company_qualification(_primary_lead())
    assert result["qualification_review_stage"] == "validated"
    assert result["qualified"] is True
    assert result["potential_routes"] == ["Thorio"]
    assert result["qualification_b_result"]["independent"] is True


def test_qualification_b_rejects_tampered_primary_route_claim():
    lead = _primary_lead()
    lead["qualification_results"]["Thorio"]["route_research"]["verified"] = False
    result = apply_company_qualification(lead)
    assert result["qualification_review_stage"] == "validated"
    assert result["qualified"] is False
    assert "Thorio:route_research_not_verified" in result["qualification_b_result"]["disagreements"]


def test_verification_does_not_promote_role_evidence_and_email_to_verified():
    lead = _primary_lead()
    lead["company_research"]["decision_maker_verification_status"] = "observed_needs_role_verification"
    lead["company_research"]["decision_maker_title"] = "Chief Technology Officer"
    result = verification("verification", {"lead": lead, "evidence_events": []}, None)
    assert result["decision_maker_verification"] == "observed_needs_role_verification"
    assert result["decision_maker_role_evidence"] == ""


def test_verification_does_not_promote_observed_person_without_role_and_contact_evidence():
    lead = _primary_lead()
    lead["company_research"]["decision_maker_verification_status"] = "observed_needs_role_verification"
    lead["company_research"].pop("decision_maker_title", None)
    lead["company_research"].pop("decision_maker_email", None)
    lead.pop("contact_email", None)
    result = verification("verification", {"lead": lead, "evidence_events": []}, None)
    assert result["decision_maker_verification"] == "observed_needs_role_verification"


def test_verification_can_complete_research_boundary_before_route_qualification():
    now = _timestamp()
    verified_ref = lambda text: {"url": "https://example.com/evidence", "evidence": text, "observed_at": now}
    lead = _primary_lead()
    lead["research_status"] = "research_required"
    lead["potential_routes"] = []
    lead["company_research"].update({
        "decision_maker": None,
        "decision_maker_evidence": None,
        "decision_maker_verification_status": "observed_needs_role_verification",
        "observed_decision_maker": "Alex CTO",
        "public_web_research": {"pages_attempted": 3},
    })
    lead["business_need_research"] = {"verified": False, "verification_status": "observed_evidence", "evidence": [verified_ref("Acme needs engineering support.")]}
    lead["current_intent_research"] = {"verified": False, "verification_status": "observed_evidence", "evidence": [verified_ref("Acme is hiring a remote software engineer now.")]}
    lead["technical_product_hiring_research"] = {"verified": False, "verification_status": "observed_evidence", "evidence": [verified_ref("Acme is hiring software engineers.")]}
    lead["commercial_research"] = {"verified": False, "verification_status": "observed_evidence", "evidence": [verified_ref("Acme offers enterprise software.")]}
    lead["route_research"] = {
        "verified": False,
        "verification_status": "observed_evidence",
        "routes": {
            "Thorio": {"verified": False, "verification_status": "observed_evidence", "evidence": [verified_ref("Acme is hiring a remote software engineer now.")]},
            "Shiftr": {"verified": False, "verification_status": "observed_evidence", "evidence": [verified_ref("Acme is hiring a remote software engineer now.")]},
            "Paxus": {"verified": False, "verification_status": "research_required", "evidence": []},
        },
    }
    lead["specialist_findings"] = {
        "social_decision_maker_research": {
            "findings": [{
                "url": "https://example.com/alex",
                "evidence": "Alex CTO is a technology leader at Acme.",
                "matches": ["CTO"],
                "source": "LinkedIn",
            }]
        }
    }
    result = verification("verification", {"lead": lead, "evidence_events": []}, None)
    assert result["decision_maker_verification"] == "verified"
    assert result["verified"] is True
    updates = result["research_section_updates"]
    assert all(updates[name]["verified"] is True for name in (
        "business_need_research",
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
    ))
    assert updates["route_research"]["routes"]["Thorio"]["verified"] is True
    assert updates["route_research"]["routes"]["Shiftr"]["verified"] is True
    assert updates["route_research"]["routes"]["Paxus"]["verified"] is False
