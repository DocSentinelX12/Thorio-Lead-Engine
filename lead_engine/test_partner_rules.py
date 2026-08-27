from lead_engine.partner_rules import (
    route_matches_partner,
    supported_partner_routes,
    validate_partner_route,
)


def test_supported_partner_routes():
    assert supported_partner_routes() == [
        "Shiftr",
        "Paxus",
        "Thorio",
    ]


def test_shiftr_matches_technology_lead():
    assert route_matches_partner(
        "Shiftr",
        signal="remote software engineer",
        evidence="Company is hiring a software engineer.",
    )


def test_thorio_matches_remote_technology_lead():
    assert route_matches_partner(
        "Thorio",
        signal="remote product designer",
        evidence="Company is hiring a remote product designer.",
    )


def test_paxus_matches_staffing_lead():
    assert route_matches_partner(
        "Paxus",
        signal="contract staffing need",
        evidence="Company needs contractors for an upcoming project.",
    )


def test_generic_hiring_does_not_match_shiftr():
    assert not route_matches_partner(
        "Shiftr",
        signal="hiring",
        evidence="Company is hiring.",
    )


def test_generic_hiring_does_not_match_thorio():
    assert not route_matches_partner(
        "Thorio",
        signal="hiring",
        evidence="Company is hiring.",
    )


def test_unsupported_route_is_invalid():
    result = validate_partner_route(
        {
            "route": "Review",
            "company": "Acme",
            "signal": "remote software engineer",
            "evidence": "Acme is hiring a remote software engineer.",
        }
    )

    assert result["valid"] is False
    assert result["reason"] == "unsupported_route"


def test_route_evidence_mismatch_is_invalid():
    result = validate_partner_route(
        {
            "route": "Shiftr",
            "company": "Acme",
            "signal": "office manager",
            "evidence": "Acme is hiring an office manager.",
        }
    )

    assert result["valid"] is False
    assert result["reason"] == "route_evidence_mismatch"


def test_valid_route_is_valid():
    result = validate_partner_route(
        {
            "route": "Shiftr",
            "company": "Acme",
            "signal": "remote software engineer",
            "evidence": "Acme is hiring a remote software engineer.",
        }
    )

    assert result["valid"] is True
    assert result["reason"] == ""
