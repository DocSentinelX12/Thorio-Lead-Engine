from lead_engine.delivery_policy import MIN_DELIVERY_SCORE
from lead_engine.partner_export import build_partner_exports


def make_lead(route, company, signal, evidence, eligible_routes=None):
    return {
        "source": "linkedin",
        "source_id": f"{company}-001",
        "fingerprint": f"fp-{company}",
        "url": "https://example.com/jobs/123",
        "company": company,
        "person": "Jane Smith",
        "contact_name": "Jane Smith",
        "contact_title": "CTO",
        "contact_email": "jane@example.com",
        "signal": signal,
        "evidence": evidence,
        "business_need": "Build a technical team",
        "route": route,
        "potential_routes": [route],
        "lead_score": MIN_DELIVERY_SCORE,
        "priority": "High",
        "status": "qualified",
        "qualified": True,
        "qualification_status": "qualified",
        "eligible_routes": eligible_routes if eligible_routes is not None else [route],
    }


def test_build_partner_exports_routes_machine_eligible_leads_by_partner():
    leads = [
        make_lead("Thorio", "Remote Tech", "remote software engineer", "Remote Tech is hiring a remote software engineer."),
        make_lead("Shiftr", "AI Systems", "technology implementation project", "AI Systems has a technology implementation project."),
        make_lead("Paxus", "Enterprise Corp", "technology consulting project", "Enterprise Corp needs technology consulting."),
    ]
    result = build_partner_exports(leads)
    assert len(result["Thorio"]) == 1
    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1
    assert result["Thorio"][0]["company"] == "Remote Tech"
    assert result["Shiftr"][0]["company"] == "AI Systems"
    assert result["Paxus"][0]["company"] == "Enterprise Corp"


def test_partner_export_preserves_qualification_context():
    lead = make_lead("Shiftr", "Context Corp", "technology implementation project", "Context Corp has a technology implementation project.")
    result = build_partner_exports([lead])["Shiftr"][0]
    assert result["fingerprint"] == "fp-Context Corp"
    assert result["business_need"] == "Build a technical team"
    assert result["qualified"] is True
    assert result["qualification_status"] == "qualified"


def test_partner_export_does_not_require_human_approval():
    lead = make_lead("Shiftr", "Autonomous Corp", "technology implementation project", "Autonomous Corp has a technology implementation project.")
    assert "approval_status" not in lead
    assert "human_approved" not in lead
    assert build_partner_exports([lead])["Shiftr"][0]["company"] == "Autonomous Corp"


def test_route_evidence_mismatch_cannot_be_exported():
    lead = make_lead("Shiftr", "Mismatch Corp", "office manager", "Mismatch Corp is hiring an office manager.")
    assert build_partner_exports([lead])["Shiftr"] == []


def test_build_partner_exports_does_not_duplicate_leads():
    lead = make_lead("Shiftr", "Multi Route Corp", "technology project", "Multi Route Corp has a technology project.", approved_routes=["Shiftr"])
    lead["potential_routes"] = ["Shiftr", "Paxus"]
    result = build_partner_exports([lead])
    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 0


def test_build_partner_exports_handles_empty_input():
    result = build_partner_exports([])
    assert result["Thorio"] == []
    assert result["Shiftr"] == []
    assert result["Paxus"] == []


def test_unsupported_route_is_not_exported():
    lead = make_lead("UnknownPartner", "Unknown Corp", "remote software engineer", "Unknown Corp is hiring a remote software engineer.")
    result = build_partner_exports([lead])
    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert result["Thorio"] == []
