from .lead_group import (
    group_leads_by_company,
    group_leads_by_route,
)


def test_group_leads_by_route():
    leads = [
        {"company": "A", "route": "Shiftr"},
        {"company": "B", "route": "Paxus"},
        {"company": "C", "route": "Shiftr"},
    ]

    result = group_leads_by_route(leads)

    assert [
        lead["company"]
        for lead in result["Shiftr"]
    ] == ["A", "C"]

    assert [
        lead["company"]
        for lead in result["Paxus"]
    ] == ["B"]


def test_group_leads_by_route_ignores_blank_routes():
    leads = [
        {"company": "A", "route": ""},
        {"company": "B", "route": "Thorio"},
    ]

    result = group_leads_by_route(leads)

    assert result == {
        "Thorio": [
            {"company": "B", "route": "Thorio"}
        ]
    }


def test_group_leads_by_route_copies_records():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
    }

    result = group_leads_by_route([lead])

    assert result["Shiftr"][0] == lead
    assert result["Shiftr"][0] is not lead


def test_group_leads_by_company():
    leads = [
        {"company": "Acme", "route": "Shiftr"},
        {"company": "Beta", "route": "Paxus"},
        {"company": "Acme", "route": "Thorio"},
    ]

    result = group_leads_by_company(leads)

    assert [
        lead["route"]
        for lead in result["acme"]
    ] == ["Shiftr", "Thorio"]

    assert len(result["beta"]) == 1


def test_group_leads_by_company_normalizes_case():
    leads = [
        {"company": "ACME"},
        {"company": "acme"},
        {"company": " AcMe "},
    ]

    result = group_leads_by_company(leads)

    assert len(result["acme"]) == 3


def test_group_leads_by_company_ignores_blank_company():
    leads = [
        {"company": ""},
        {"company": "Acme"},
    ]

    result = group_leads_by_company(leads)

    assert list(result) == ["acme"]
    assert len(result["acme"]) == 1


def test_group_empty_leads():
    assert group_leads_by_route([]) == {}
    assert group_leads_by_company([]) == [] or group_leads_by_company([]) == {}
