from lead_engine.delivery_policy import MIN_DELIVERY_SCORE
from lead_engine.export import (
    export_all_partners,
    export_partner_leads,
)


def make_lead(
    company,
    route,
    signal,
    evidence,
):
    return {
        "company": company,
        "route": route,
        "signal": signal,
        "evidence": evidence,
        "url": "https://example.com/jobs/123",
        "lead_score": MIN_DELIVERY_SCORE,
        "approval_status": "approved",
        "human_approved": True,
        "approval_required": False,
        "approved_routes": [route],
    }


def test_export_partner_leads_returns_requested_partner():
    leads = [
        make_lead(
            "Shiftr Lead",
            "Shiftr",
            "technology engineering project",
            "Shiftr Lead has a technology engineering project.",
        ),
        make_lead(
            "Paxus Lead",
            "Paxus",
            "contract staffing need",
            "Paxus Lead needs contract staffing.",
        ),
        make_lead(
            "Thorio Lead",
            "Thorio",
            "remote software engineer",
            "Thorio Lead is hiring a remote software engineer.",
        ),
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
        make_lead(
            "A",
            "Shiftr",
            "technology engineering project",
            "A has a technology engineering project.",
        ),
        make_lead(
            "B",
            "Paxus",
            "contract staffing need",
            "B needs contract staffing.",
        ),
        make_lead(
            "C",
            "Thorio",
            "remote software engineer",
            "C is hiring a remote software engineer.",
        ),
    ]

    result = export_all_partners(leads)

    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1
    assert len(result["Thorio"]) == 1


def test_export_partner_leads_requires_human_approval():
    lead = make_lead(
        "Pending Corp",
        "Shiftr",
        "technology engineering project",
        "Pending Corp has a technology engineering project.",
    )

    lead["approval_status"] = "pending"
    lead["human_approved"] = False
    lead["approval_required"] = True
    lead["approved_routes"] = []

    result = export_partner_leads(
        [lead],
        "Shiftr",
    )

    assert result == []


def test_export_partner_leads_requires_route_specific_approval():
    lead = make_lead(
        "Wrong Route Corp",
        "Paxus",
        "contract staffing need",
        "Wrong Route Corp needs contract staffing.",
    )

    lead["approved_routes"] = ["Shiftr"]

    result = export_partner_leads(
        [lead],
        "Paxus",
    )

    assert result == []
