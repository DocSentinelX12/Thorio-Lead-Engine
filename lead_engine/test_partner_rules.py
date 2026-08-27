from lead_engine.partner_rules import (
    normalize_text,
    route_matches_partner,
    supported_partner_routes,
    validate_partner_route,
)


def test_normalize_text():
    assert normalize_text("  Remote   Software Engineer  ") == (
        "remote software engineer"
    )


def test_shiftr_matches_technical_signal():
    assert route_matches_partner(
        route="Shiftr",
        signal="software engineer",
        evidence="Company needs a software engineer.",
        company="Acme",
    )


def test_paxus_matches_staffing_signal():
    assert route_matches_partner(
        route="Paxus",
        signal="contract staffing",
        evidence="Company needs contract staffing support.",
        company="Acme",
    )


def test_thorio_matches_remote_signal():
    assert route_matches_partner(
        route="Thorio",
        signal="remote product designer",
        evidence="Company is hiring a remote product designer.",
        company="Acme",
    )


def test_generic_hiring_does_not_match_shiftr():
    assert not route_matches_partner(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
        company="Acme",
    )


def test_company_name_substring_does_not_create_route_match():
    assert not route_matches_partner(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
        company="QualityTestCo",
    )


def test_it_does_not_match_inside_unrelated_words():
    assert not route_matches_partner(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
        company="QualityTestCo",
    )


def test_ai_does_not_match_inside_unrelated_words():
    assert not route_matches_partner(
        route="Thorio",
        signal="office manager",
        evidence="Company is hiring an office manager.",
        company="TrainingCompany",
    )


def test_unknown_route_does_not_match():
    assert not route_matches_partner(
        route="UnknownPartner",
        signal="software engineer",
        evidence="Company needs a software engineer.",
        company="Acme",
    )


def test_validate_partner_route_returns_valid_result():
    result = validate_partner_route(
        {
            "route": "Shiftr",
            "signal": "software engineer",
            "evidence": "Company needs a software engineer.",
            "company": "Acme",
        }
    )

    assert result == {
        "valid": True,
        "route": "Shiftr",
        "reason": "",
    }


def test_validate_partner_route_rejects_mismatch():
    result = validate_partner_route(
        {
            "route": "Shiftr",
            "signal": "office manager",
            "evidence": "Company is hiring an office manager.",
            "company": "QualityTestCo",
        }
    )

    assert result == {
        "valid": False,
        "route": "Shiftr",
        "reason": "route_evidence_mismatch",
    }


def test_supported_partner_routes():
    assert supported_partner_routes() == [
        "Shiftr",
        "Paxus",
        "Thorio",
    ]
