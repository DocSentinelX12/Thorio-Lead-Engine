from lead_engine.delivery import (
    SUPPORTED_ROUTES,
    build_delivery_batches,
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
