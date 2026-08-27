from lead_engine.partner_delivery import (
    PARTNER_ORDER,
    partner_delivery_summary,
    prepare_partner_delivery,
)


def test_prepare_partner_delivery_returns_all_partners():
    leads = [
        {
            "company": "Shiftr Lead",
            "route": "Shiftr",
        },
        {
            "company": "Paxus Lead",
            "route": "Paxus",
        },
        {
            "company": "Thorio Lead",
            "route": "Thorio",
        },
    ]

    result = prepare_partner_delivery(leads)

    assert tuple(result.keys()) == PARTNER_ORDER
    assert result["Shiftr"][0]["company"] == "Shiftr Lead"
    assert result["Paxus"][0]["company"] == "Paxus Lead"
    assert result["Thorio"][0]["company"] == "Thorio Lead"


def test_partner_delivery_summary():
    leads = [
        {"company": "A", "route": "Shiftr"},
        {"company": "B", "route": "Shiftr"},
        {"company": "C", "route": "Paxus"},
        {"company": "D", "route": "Thorio"},
        {"company": "E", "route": "Review"},
    ]

    result = partner_delivery_summary(leads)

    assert result["counts"] == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 1,
    }

    assert result["total"] == 4


def test_review_leads_are_not_prepared_for_delivery():
    leads = [
        {
            "company": "Needs Review",
            "route": "Review",
        }
    ]

    result = prepare_partner_delivery(leads)

    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert result["Thorio"] == []
