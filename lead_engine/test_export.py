from lead_engine.delivery_policy import MIN_DELIVERY_SCORE
from lead_engine.export import export_all_partners, export_partner_leads


def make_lead(company, route, signal, evidence):
    return {
        "company": company,
        "person": "Jane Doe",
        "route": route,
        "signal": signal,
        "evidence": evidence,
        "business_need": "Build a technical team",
        "url": "https://example.com/jobs/123",
        "lead_score": MIN_DELIVERY_SCORE,
        "status": "qualified",
        "qualified": True,
        "qualification_status": "qualified",
        "eligible_routes": [route],
    }


def test_export_partner_leads_returns_requested_partner():
    leads = [
        make_lead("Shiftr Lead", "Shiftr", "technology engineering project", "Shiftr Lead has a technology engineering project."),
        make_lead("Paxus Lead", "Paxus", "contract staffing need", "Paxus Lead needs contract staffing."),
        make_lead("Thorio Lead", "Thorio", "remote software engineer", "Thorio Lead is hiring a remote software engineer."),
    ]
    result = export_partner_leads(leads, "Shiftr")
    assert len(result) == 1
    assert result[0]["company"] == "Shiftr Lead"


def test_export_partner_leads_rejects_unknown_partner():
    assert export_partner_leads([{"company": "Unknown", "route": "Review"}], "Unknown") == []


def test_export_all_partners_groups_leads():
    leads = [
        make_lead("A", "Shiftr", "technology engineering project", "A has a technology engineering project."),
        make_lead("B", "Paxus", "contract staffing need", "B needs contract staffing."),
        make_lead("C", "Thorio", "remote software engineer", "C is hiring a remote software engineer."),
    ]
    result = export_all_partners(leads)
    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1
    assert len(result["Thorio"]) == 1


def test_export_does_not_require_human_approval():
    lead = make_lead("Autonomous Corp", "Shiftr", "technology engineering project", "Autonomous Corp has a technology engineering project.")
    assert "approval_status" not in lead
    assert "human_approved" not in lead
    assert export_partner_leads([lead], "Shiftr")[0]["company"] == "Autonomous Corp"


def test_export_requires_machine_eligible_route():
    lead = make_lead("Wrong Route Corp", "Paxus", "contract staffing need", "Wrong Route Corp needs contract staffing.")
    lead["eligible_routes"] = ["Shiftr"]
    assert export_partner_leads([lead], "Paxus") == []
