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
        "signal": "Acme is hiring software engineers",
        "evidence": "Acme is hiring software engineers",
        "observed_at": now,
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Alex CTO",
            "decision_maker_evidence": "Alex CTO was named in the source evidence.",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "alex@example.com",
        },
        "business_need_research": {
            "verified": True,
            "verification_status": "verified",
            "business_need": "Acme is hiring software engineers",
            "observed_at": now,
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "Acme is hiring software engineers",
            "observed_at": now,
        },
        "route_research": {
            "verified": True,
            "verification_status": "verified",
            "routes": {
                "Thorio": {
                    "verified": True,
                    "verification_status": "verified",
                    "evidence": "Acme has a current software engineering hiring need suitable for Thorio.",
                },
                "Shiftr": {"verified": False, "evidence": ""},
                "Paxus": {"verified": False, "evidence": ""},
            },
        },
        "potential_routes": ["Thorio"],
        "qualification_results": {
            "Thorio": {
                "qualified": True,
                "category_score": 1,
                "matched_category": True,
                "current_need": {"qualified": True, "observed_at": now, "evidence": "Acme is hiring software engineers"},
                "recent_inquiry": {"qualified": False, "observed_at": None},
                "route_research": {"verified": True, "evidence": "Acme has a current software engineering hiring need suitable for Thorio."},
            }
        },
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
