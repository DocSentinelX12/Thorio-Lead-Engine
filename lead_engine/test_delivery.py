from lead_engine.delivery import (
    build_delivery_batches,
    delivery_counts,
    total_deliverable_leads,
)


def test_build_delivery_batches_groups_leads_by_partner():
    leads = [
        {
            "company": "Thorio Company",
            "route": "Thorio",
            "signal": "remote software engineer",
        },
        {
            "company": "Shiftr Company",
            "route": "Shiftr",
            "signal": "technology implementation project",
        },
        {
            "company": "Paxus Company",
            "route": "Paxus",
            "signal": "technology consulting project",
        },
    ]

    result = build_delivery_batches(leads)

    assert len(result["Thorio"]) == 1
    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1

    assert result["Thorio"][0]["company"] == "Thorio Company"
    assert result["Shiftr"][0]["company"] == "Shiftr Company"
    assert result["Paxus"][0]["company"] == "Paxus Company"


def test_review_leads_are_not_delivered():
    leads = [
        {
            "company": "Review Company",
            "route": "Review",
            "signal": "unclear opportunity",
        }
    ]

    result = build_delivery_batches(leads)

    assert result["Thorio"] == []
    assert result["Shiftr"] == []
    assert result["Paxus"] == []


def test_delivery_counts():
    leads = [
        {"company": "A", "route": "Thorio"},
        {"company": "B", "route": "Thorio"},
        {"company": "C", "route": "Shiftr"},
        {"company": "D", "route": "Paxus"},
    ]

    assert delivery_counts(leads) == {
        "Thorio": 2,
        "Shiftr": 1,
        "Paxus": 1,
    }

    assert total_deliverable_leads(leads) == 4
