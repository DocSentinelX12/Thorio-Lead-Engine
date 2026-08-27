from lead_engine.delivery import (
    SUPPORTED_ROUTES,
    build_delivery_batches,
    delivery_counts,
)


def test_supported_routes_are_defined():
    assert SUPPORTED_ROUTES == (
        "Shiftr",
        "Paxus",
        "Thorio",
    )


def test_delivery_batches_group_leads_by_partner():
    leads = [
        {"company": "Alpha", "route": "Shiftr"},
        {"company": "Beta", "route": "Paxus"},
        {"company": "Gamma", "route": "Thorio"},
        {"company": "Delta", "route": "Shiftr"},
    ]

    result = build_delivery_batches(leads)

    assert [lead["company"] for lead in result["Shiftr"]] == [
        "Alpha",
        "Delta",
    ]
    assert [lead["company"] for lead in result["Paxus"]] == [
        "Beta",
    ]
    assert [lead["company"] for lead in result["Thorio"]] == [
        "Gamma",
    ]


def test_delivery_batches_ignore_review_and_unknown_routes():
    leads = [
        {"company": "Review Lead", "route": "Review"},
        {"company": "Unknown Lead", "route": "Something Else"},
        {"company": "Valid Lead", "route": "Thorio"},
    ]

    result = build_delivery_batches(leads)

    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert len(result["Thorio"]) == 1
    assert result["Thorio"][0]["company"] == "Valid Lead"


def test_delivery_batches_copy_lead_records():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "lead_score": 90,
    }

    result = build_delivery_batches([lead])

    assert result["Shiftr"][0] == lead
    assert result["Shiftr"][0] is not lead


def test_delivery_counts():
    leads = [
        {"company": "A", "route": "Shiftr"},
        {"company": "B", "route": "Shiftr"},
        {"company": "C", "route": "Paxus"},
        {"company": "D", "route": "Thorio"},
        {"company": "E", "route": "Review"},
    ]

    assert delivery_counts(leads) == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 1,
    }


def test_delivery_counts_empty():
    assert delivery_counts([]) == {
        "Shiftr": 0,
        "Paxus": 0,
        "Thorio": 0,
    }
