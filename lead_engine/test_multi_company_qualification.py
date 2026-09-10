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
    result = evaluate_company_qualification(_lead("technology recruitment support", "The company is seeking technology recruitment support."))
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


def test_stale_signal_does_not_qualify():
    result = evaluate_company_qualification(_lead("software developer hiring", "Old hiring announcement.", need_at="2025-01-01T00:00:00+00:00", discovered_at=NOW))
    assert result["qualified_companies"] == []


def test_current_need_signal_can_use_verified_discovery_observation_time():
    result = evaluate_company_qualification(_lead("software developer hiring", "Current hiring signal observed by the collector.", need_at="", discovery_timestamp=NOW))
    assert result["qualified_companies"] == ["Shiftr"]
    assert result["companies"]["Shiftr"]["current_need"]["observed_at"] is not None


def test_missing_paxus_verification_does_not_destroy_paxus_qualification():
    result = apply_company_qualification(_lead("technology recruitment support", "We are seeking technology recruitment support."))
    assert result["qualified"] is True
    assert result["potential_routes"] == ["Paxus"]
    assert result["qualification_results"]["Paxus"]["qualified"] is True
    assert result["qualification_results"]["Paxus"]["true_referral"] is False
    assert result["research_status"] == "research_required"
