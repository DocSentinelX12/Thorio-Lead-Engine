from .lead_filter import (
    filter_approved_leads,
    filter_leads,
)


def make_lead(
    company,
    route="Thorio",
    score=80,
    status="qualified",
    delivery_status="approved",
):
    return {
        "company": company,
        "route": route,
        "lead_score": score,
        "status": status,
        "delivery_status": delivery_status,
    }


def test_filter_by_route():
    leads = [
        make_lead("A", route="Shiftr"),
        make_lead("B", route="Paxus"),
        make_lead("C", route="Shiftr"),
    ]

    result = filter_leads(
        leads,
        route="Shiftr",
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C"]


def test_filter_by_minimum_score():
    leads = [
        make_lead("A", score=90),
        make_lead("B", score=50),
        make_lead("C", score=75),
    ]

    result = filter_leads(
        leads,
        minimum_score=75,
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C"]


def test_filter_by_status():
    leads = [
        make_lead("A", status="qualified"),
        make_lead("B", status="new"),
        make_lead("C", status="qualified"),
    ]

    result = filter_leads(
        leads,
        status="qualified",
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C"]


def test_filters_are_combined():
    leads = [
        make_lead(
            "A",
            route="Shiftr",
            score=90,
            status="qualified",
        ),
        make_lead(
            "B",
            route="Shiftr",
            score=50,
            status="qualified",
        ),
        make_lead(
            "C",
            route="Paxus",
            score=90,
            status="qualified",
        ),
    ]

    result = filter_leads(
        leads,
        route="Shiftr",
        minimum_score=80,
        status="qualified",
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A"]


def test_empty_result():
    result = filter_leads(
        [make_lead("A")],
        route="Shiftr",
    )

    assert result == []


def test_filter_returns_copies():
    lead = make_lead("Acme")

    result = filter_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_filter_approved_leads():
    leads = [
        make_lead(
            "Approved",
            delivery_status="approved",
        ),
        make_lead(
            "Pending",
            delivery_status="pending",
        ),
        make_lead(
            "Rejected",
            delivery_status="rejected",
        ),
    ]

    result = filter_approved_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["Approved"]


def test_filter_approved_leads_is_case_insensitive():
    lead = make_lead(
        "Acme",
        delivery_status=" APPROVED ",
    )

    result = filter_approved_leads([lead])

    assert len(result) == 1
    assert result[0]["company"] == "Acme"


def test_filter_approved_leads_empty():
    assert filter_approved_leads([]) == []
