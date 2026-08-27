from .lead_routes import (
    route_counts,
    route_leads,
)


def test_route_leads():
    leads = [
        {"company": "A", "route": "Shiftr"},
        {"company": "B", "route": "Paxus"},
        {"company": "C", "route": "Thorio"},
    ]

    result = route_leads(leads)

    assert result["Shiftr"][0]["company"] == "A"
    assert result["Paxus"][0]["company"] == "B"
    assert result["Thorio"][0]["company"] == "C"
    assert result["Review"] == []


def test_unknown_route_goes_to_review():
    leads = [
        {"company": "A", "route": "Unknown"},
        {"company": "B", "route": ""},
        {"company": "C"},
    ]

    result = route_leads(leads)

    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert result["Thorio"] == []
    assert [
        lead["company"]
        for lead in result["Review"]
    ] == ["A", "B", "C"]


def test_route_leads_preserves_order():
    leads = [
        {"company": "A", "route": "Shiftr"},
        {"company": "B", "route": "Shiftr"},
        {"company": "C", "route": "Shiftr"},
    ]

    result = route_leads(leads)

    assert [
        lead["company"]
        for lead in result["Shiftr"]
    ] == ["A", "B", "C"]


def test_route_leads_returns_copies():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
    }

    result = route_leads([lead])

    assert result["Shiftr"][0] == lead
    assert result["Shiftr"][0] is not lead


def test_route_counts():
    leads = [
        {"route": "Shiftr"},
        {"route": "Shiftr"},
        {"route": "Paxus"},
        {"route": "Thorio"},
        {"route": "Unknown"},
    ]

    assert route_counts(leads) == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 1,
        "Review": 1,
    }


def test_route_counts_empty():
    assert route_counts([]) == {
        "Shiftr": 0,
        "Paxus": 0,
        "Thorio": 0,
        "Review": 0,
    }
