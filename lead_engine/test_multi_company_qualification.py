from datetime import datetime, timezone

from .qualification import apply_company_qualification, evaluate_company_qualification

NOW = datetime.now(timezone.utc).isoformat()


def _lead(signal, evidence, **extra):
    lead = {
        "company": "ExampleCo",
        "signal": signal,
        "evidence": evidence,
        "discovered_at": NOW,
        "need_at": NOW,
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": extra.get("contact_name", "Jane Doe"),
            "decision_maker_evidence": "https://example.com/leadership",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "jane@example.com",
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": evidence,
            "observed_at": NOW,
            "evidence_url": "https://example.com/research/intent",
        },
        "business_need_research": {
            "verified": True,
            "verification_status": "verified",
            "business_need": evidence,
            "evidence_url": "https://example.com/research/need",
        },
        "route_research": {
            "verified": True,
            "verification_status": "verified",
            "routes": {
                "Shiftr": {"verified": True, "evidence": "Verified service need evidence."},
                "Thorio": {"verified": True, "evidence": "Verified technical hiring evidence."},
                "Paxus": {"verified": True, "evidence": "Verified technical talent need evidence."},
            },
        },
    }
    lead.update(extra)
    return lead


def test_shiftr_only():
    result = evaluate_company_qualification(_lead("software developer hiring", "We are hiring a software developer."))
    assert result["qualified_companies"] == ["Shiftr"]
    assert result["companies"]["Shiftr"]["qualified"] is True
    assert result["companies"]["Thorio"]["qualified"] is False
    assert result["companies"]["Paxus"]["qualified"] is False


def test_thorio_only():
    result = evaluate_company_qualification(_lead("remote product manager", "Remote product manager opening."))
    assert result["qualified_companies"] == ["Thorio"]
    assert result["companies"]["Thorio"]["qualified"] is True
    assert result["companies"]["Shiftr"]["qualified"] is False
    assert result["companies"]["Paxus"]["qualified"] is False


def test_paxus_qualified_but_true_referral_waits_for_research_and_verification():
    result = evaluate_company_qualification(_lead("technology recruitment support", "The company is seeking technology recruitment support.", contact_name=""))
    paxus = result["companies"]["Paxus"]
    assert paxus["qualified"] is True
    assert paxus["true_referral"] is False
    assert paxus["referral_status"] == "research_required"
    assert "named_hiring_contact" in paxus["referral_checklist"]["failures"]


def test_true_paxus_referral_requires_all_existing_gates():
    result = evaluate_company_qualification(_lead("technology recruitment support", "The company is seeking technology recruitment support.", contact_name="Jane Doe", contact_communicated=True, contact_consent=True))
    paxus = result["companies"]["Paxus"]
    assert paxus["qualified"] is True
    assert paxus["true_referral"] is True
    assert paxus["referral_status"] == "true_referral"
    assert paxus["referral_checklist"]["failures"] == []


def test_shiftr_and_thorio_both_remain_qualified():
    result = evaluate_company_qualification(_lead("remote software engineer", "We are hiring a remote software engineer and need a development team."))
    assert "Shiftr" in result["qualified_companies"]
    assert "Thorio" in result["qualified_companies"]


def test_shiftr_and_paxus_are_independent():
    result = evaluate_company_qualification(_lead("software development contractor and technology recruitment support", "We need a software development contractor and technology recruitment support."))
    assert "Shiftr" in result["qualified_companies"]
    assert "Paxus" in result["qualified_companies"]
    assert result["companies"]["Paxus"]["true_referral"] is False


def test_thorio_and_paxus_are_independent():
    result = evaluate_company_qualification(_lead("remote software engineer and technology recruitment support", "We are hiring a remote software engineer and need technology recruitment support."))
    assert "Thorio" in result["qualified_companies"]
    assert "Paxus" in result["qualified_companies"]
    assert result["companies"]["Paxus"]["true_referral"] is False


def test_all_three_are_preserved():
    result = evaluate_company_qualification(_lead("remote software engineer, software development contractor, technology recruitment support", "We are hiring a remote software engineer, need a development contractor, and need technology recruitment support."))
    assert set(result["qualified_companies"]) == {"Shiftr", "Thorio", "Paxus"}
    assert result["companies"]["Paxus"]["qualified"] is True


def test_shiftr_service_delivery_need_can_qualify_without_employee_hiring_language():
    result = evaluate_company_qualification(_lead("AI agent development", "We need help building AI agents for our SaaS product."))
    assert result["qualified_companies"] == ["Shiftr"]
    assert result["companies"]["Shiftr"]["qualified"] is True
    assert result["companies"]["Paxus"]["qualified"] is False
    assert result["companies"]["Thorio"]["qualified"] is False


def test_shiftr_service_need_can_overlap_with_thorio_when_remote_hiring_is_present():
    result = evaluate_company_qualification(_lead("remote software engineer and AI development", "We are hiring a remote software engineer and need an AI development team."))
    assert "Shiftr" in result["qualified_companies"]
    assert "Thorio" in result["qualified_companies"]
    assert "Paxus" not in result["qualified_companies"]


def test_stale_researched_intent_does_not_qualify():
    stale = _lead("software developer hiring", "Old hiring announcement.")
    stale["current_intent_research"]["observed_at"] = "2025-01-01T00:00:00+00:00"
    result = evaluate_company_qualification(stale)
    assert result["qualified_companies"] == []


def test_raw_discovery_timestamp_cannot_be_used_as_researched_intent():
    lead = _lead("software developer hiring", "Current hiring signal observed by the collector.")
    lead["research_status"] = "research_required"
    lead.pop("current_intent_research")
    lead.pop("business_need_research")
    lead.pop("route_research")
    lead["need_at"] = ""
    lead["discovery_timestamp"] = NOW
    result = evaluate_company_qualification(lead)
    assert result["qualified_companies"] == []
    assert result["research_status"] == "research_required"


def test_missing_paxus_verification_does_not_destroy_paxus_qualification():
    result = apply_company_qualification(_lead("technology recruitment support", "We are seeking technology recruitment support.", contact_name=""))
    assert result["qualified"] is True
    assert result["potential_routes"] == ["Paxus"]
    assert result["qualification_results"]["Paxus"]["qualified"] is True
    assert result["qualification_results"]["Paxus"]["true_referral"] is False
    assert result["research_status"] == "complete"
