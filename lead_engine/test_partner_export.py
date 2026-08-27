from lead_engine.partner_export import (
    build_partner_exports,
)


def test_build_partner_exports_routes_leads_by_partner():
    leads = [
        {
            "company": "Remote Tech",
            "signal": "remote software engineer",
            "route": "Thorio",
            "potential_routes": ["Thorio"],
        },
        {
            "company": "AI Systems",
            "signal": "AI implementation project",
            "route": "Shiftr",
            "potential_routes": ["Shiftr"],
        },
        {
            "company": "Enterprise Corp",
            "signal": "technology consulting project",
            "route": "Paxus",
            "potential_routes": ["Paxus"],
        },
    ]

    result = build_partner_exports(leads)

    assert "Thorio" in result
    assert "Shiftr" in result
    assert "Paxus" in result

    assert result["Thorio"][0]["company"] == "Remote Tech"
    assert result["Shiftr"][0]["company"] == "AI Systems"
    assert result["Paxus"][0]["company"] == "Enterprise Corp"


def test_build_partner_exports_does_not_duplicate_leads():
    leads = [
        {
            "company": "Multi Route Corp",
            "signal": "technology project",
            "route": "Shiftr",
            "potential_routes": [
                "Shiftr",
                "Paxus",
            ],
        },
    ]

    result = build_partner_exports(leads)

    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 0
    assert result["Shiftr"][0]["company"] == "Multi Route Corp"


def test_build_partner_exports_handles_empty_input():
    result = build_partner_exports([])

    assert result["Thorio"] == []
    assert result["Shiftr"] == []
    assert result["Paxus"] == []
