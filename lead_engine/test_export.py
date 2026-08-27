from lead_engine.export import (
    export_all_partners,
    export_partner_leads,
)


def test_export_partner_leads_returns_requested_partner():
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

    result = export_partner_leads(
        leads,
        "Shiftr",
    )

    assert len(result) == 1
    assert result[0]["company"] == "Shiftr Lead"


def test_export_partner_leads_rejects_unknown_partner():
    result = export_partner_leads(
        [
            {
                "company": "Unknown",
                "route": "Review",
            }
        ],
        "Unknown",
    )

    assert result == []


def test_export_all_partners_groups_leads():
    leads = [
        {
            "company": "A",
            "route": "Shiftr",
        },
        {
            "company": "B",
            "route": "Paxus",
        },
        {
            "company": "C",
            "route": "Thorio",
        },
    ]

    result = export_all_partners(leads)

    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1
    assert len(result["Thorio"]) == 1
