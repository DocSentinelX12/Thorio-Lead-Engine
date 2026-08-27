from .scoring import (
    priority_from_score,
    route_score_result,
    score_lead,
    score_result,
    score_route,
)


def test_software_engineer_is_strong_signal():
    score = score_lead(
        company="Acme",
        signal="software engineer hiring",
        evidence="Acme is hiring a software engineer.",
    )

    assert score >= 7


def test_remote_engineer_scores_higher_than_generic_engineer():
    generic = score_lead(
        company="Acme",
        signal="software engineer",
        evidence="Acme is hiring a software engineer.",
    )

    remote = score_lead(
        company="Acme",
        signal="remote software engineer",
        evidence="Acme is hiring a remote software engineer.",
    )

    assert remote > generic


def test_contract_developer_is_high_intent():
    score = score_lead(
        company="Acme",
        signal="contract developer",
        evidence="Acme needs a contract developer.",
    )

    assert score >= 8


def test_technology_staffing_is_strong_paxus_signal():
    score = score_lead(
        company="StaffCo",
        signal="technology staffing",
        evidence="Company needs technology staffing.",
    )

    assert score >= 9


def test_remote_product_designer_is_thorio_signal():
    score = score_lead(
        company="DesignCo",
        signal="remote product designer",
        evidence="Company is hiring a remote product designer.",
    )

    assert score >= 8


def test_unrelated_lead_has_zero_score():
    score = score_lead(
        company="ExampleCo",
        signal="office manager",
        evidence="Company is hiring an office manager.",
    )

    assert score == 0


def test_priority_levels():
    assert priority_from_score(0) == "Review"
    assert priority_from_score(1) == "Low"
    assert priority_from_score(6) == "Medium"
    assert priority_from_score(12) == "High"
    assert priority_from_score(20) == "Critical"


def test_score_result_returns_score_and_priority():
    result = score_result(
        company="Acme",
        signal="remote software engineer",
        evidence="Acme is hiring a remote software engineer.",
    )

    assert "lead_score" in result
    assert "priority" in result
    assert result["lead_score"] > 0


def test_route_score_returns_route_information():
    result = route_score_result(
        route="Thorio",
        company="RemoteTech",
        signal="remote product designer",
        evidence="Remote product designer opening.",
    )

    assert result["route"] == "Thorio"
    assert result["route_score"] > 0
    assert result["priority"] in {
        "Low",
        "Medium",
        "High",
        "Critical",
    }


def test_thorio_route_bonus_rewards_remote_signal():
    base = score_route(
        route="Shiftr",
        company="RemoteTech",
        signal="product designer",
        evidence="Product designer opening.",
    )

    thorio = score_route(
        route="Thorio",
        company="RemoteTech",
        signal="remote product designer",
        evidence="Remote product designer opening.",
    )

    assert thorio > base


def test_paxus_route_bonus_rewards_staffing_signal():
    shiftr = score_route(
        route="Shiftr",
        company="StaffCo",
        signal="technology staffing",
        evidence="Technology staffing need.",
    )

    paxus = score_route(
        route="Paxus",
        company="StaffCo",
        signal="technology staffing",
        evidence="Technology staffing need.",
    )

    assert paxus > shiftr


def test_scoring_does_not_qualify_lead():
    result = score_result(
        company="Acme",
        signal="remote software engineer",
        evidence="Acme is hiring a remote software engineer.",
    )

    assert "qualified" not in result
    assert "status" not in result
