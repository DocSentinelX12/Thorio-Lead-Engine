from .router import (
    potential_routes,
    route,
    score_routes,
)


def test_software_engineer_hiring_routes_to_shiftr():
    scores = score_routes(
        company="Acme",
        signal="software engineer hiring",
        evidence="Acme is hiring a software engineer.",
    )

    assert scores["Shiftr"] > 0
    assert "Shiftr" in potential_routes(
        "Acme",
        "software engineer hiring",
        "Acme is hiring a software engineer.",
    )


def test_remote_software_engineer_routes_to_shiftr_and_thorio():
    routes = potential_routes(
        "Acme",
        "remote software engineer",
        "Acme is hiring a remote software engineer.",
    )

    assert "Shiftr" in routes
    assert "Thorio" in routes


def test_technology_recruitment_routes_to_paxus():
    routes = potential_routes(
        "RecruitCo",
        "technology recruitment",
        "Company needs technology recruitment support.",
    )

    assert "Paxus" in routes


def test_it_staffing_routes_to_paxus():
    routes = potential_routes(
        "StaffCo",
        "IT staffing",
        "Company needs IT staffing.",
    )

    assert "Paxus" in routes


def test_generic_remote_company_does_not_automatically_route_to_thorio():
    routes = potential_routes(
        "RemoteCo",
        "remote company",
        "The company operates remotely.",
    )

    assert "Thorio" not in routes


def test_generic_software_company_does_not_automatically_route_to_shiftr():
    routes = potential_routes(
        "SoftwareCo",
        "software company",
        "The company builds software products.",
    )

    assert "Shiftr" not in routes


def test_multiple_routes_are_preserved():
    routes = potential_routes(
        "TechCo",
        "remote software engineer",
        "TechCo is hiring a remote software engineer.",
    )

    assert "Shiftr" in routes
    assert "Thorio" in routes
    assert len(routes) >= 2


def test_no_matching_signal_returns_review():
    result = route(
        "ExampleCo",
        "office manager",
        "Company is hiring an office manager.",
    )

    assert result == "Review"


def test_software_engineer_primary_route_is_shiftr():
    result = route(
        "Acme",
        "remote software engineer",
        "Acme is hiring a remote software engineer.",
    )

    assert result == "Shiftr"


def test_paxus_primary_route():
    result = route(
        "RecruitCo",
        "technology recruitment",
        "Company needs technology recruitment support.",
    )

    assert result == "Paxus"


def test_thorio_primary_route():
    result = route(
        "RemoteTech",
        "remote product designer",
        "Company is hiring a remote product designer.",
    )

    assert result == "Thorio"


def test_score_routes_returns_all_destinations():
    scores = score_routes(
        company="ExampleCo",
        signal="office manager",
        evidence="Hiring an office manager.",
    )

    assert set(scores.keys()) == {
        "Shiftr",
        "Paxus",
        "Thorio",
    }


def test_paxus_does_not_match_normal_technology_job_posting():
    routes = potential_routes(
        "TechCo",
        "software engineer",
        "TechCo is hiring a software engineer.",
    )

    assert "Paxus" not in routes
