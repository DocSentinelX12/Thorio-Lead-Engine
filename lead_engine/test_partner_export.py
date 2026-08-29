from lead_engine.delivery_policy import MIN_DELIVERY_SCORE
from lead_engine.partner_export import (
    build_partner_exports,
)


def make_lead(
    route,
    company,
    signal,
    evidence,
    approved_routes=None,
):
    return {
        "source": "linkedin",
        "source_id": f"{company}-001",
        "url": "https://example.com/jobs/123",
        "company": company,
        "person": "Jane Smith",
        "contact_name": "Jane Smith",
        "contact_title": "CTO",
        "contact_email": "jane@example.com",
        "signal": signal,
        "evidence": evidence,
        "route": route,
        "potential_routes": [route],
        "lead_score": MIN_DELIVERY_SCORE,
        "priority": "High",
        "status": "Qualified",
        "approval_status": "approved",
        "human_approved": True,
        "approval_required": False,
        "approved_routes": (
            approved_routes
            if approved_routes is not None
            else [route]
        ),
    }


def test_build_partner_exports_routes_approved_leads_by_partner():
    leads = [
        make_lead(
            route="Thorio",
            company="Remote Tech",
            signal="remote software engineer",
            evidence=(
                "Remote Tech is hiring a remote software engineer."
            ),
        ),
        make_lead(
            route="Shiftr",
            company="AI Systems",
            signal="AI implementation project",
            evidence=(
                "AI Systems has an AI implementation project."
            ),
        ),
        make_lead(
            route="Paxus",
            company="Enterprise Corp",
            signal="technology consulting project",
            evidence=(
                "Enterprise Corp needs technology consulting."
            ),
        ),
    ]

    result = build_partner_exports(leads)

    assert len(result["Thorio"]) == 1
    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1

    assert result["Thorio"][0]["company"] == "Remote Tech"
    assert result["Shiftr"][0]["company"] == "AI Systems"
    assert result["Paxus"][0]["company"] == "Enterprise Corp"


def test_unapproved_lead_never_enters_partner_export():
    lead = make_lead(
        route="Shiftr",
        company="Unapproved Corp",
        signal="remote software engineer",
        evidence=(
            "Unapproved Corp is hiring a remote software engineer."
        ),
        approved_routes=[],
    )

    lead["approval_status"] = "pending"
    lead["human_approved"] = False
    lead["approval_required"] = True

    result = build_partner_exports([lead])

    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert result["Thorio"] == []


def test_rejected_lead_never_enters_partner_export():
    lead = make_lead(
        route="Shiftr",
        company="Rejected Corp",
        signal="remote software engineer",
        evidence=(
            "Rejected Corp is hiring a remote software engineer."
        ),
        approved_routes=["Shiftr"],
    )

    lead["approval_status"] = "rejected"
    lead["human_approved"] = False
    lead["approval_required"] = False

    result = build_partner_exports([lead])

    assert result["Shiftr"] == []


def test_lead_approved_for_different_partner_cannot_be_exported():
    lead = make_lead(
        route="Paxus",
        company="Wrong Route Corp",
        signal="contract staffing need",
        evidence=(
            "Wrong Route Corp needs contract staffing."
        ),
        approved_routes=["Shiftr"],
    )

    result = build_partner_exports([lead])

    assert result["Paxus"] == []
    assert result["Shiftr"] == []


def test_low_quality_lead_cannot_be_exported_even_when_human_approved():
    lead = make_lead(
        route="Shiftr",
        company="Low Score Corp",
        signal="remote software engineer",
        evidence=(
            "Low Score Corp is hiring a remote software engineer."
        ),
    )

    lead["lead_score"] = MIN_DELIVERY_SCORE - 1

    result = build_partner_exports([lead])

    assert result["Shiftr"] == []


def test_route_evidence_mismatch_cannot_be_exported():
    lead = make_lead(
        route="Shiftr",
        company="Mismatch Corp",
        signal="office manager",
        evidence=(
            "Mismatch Corp is hiring an office manager."
        ),
    )

    result = build_partner_exports([lead])

    assert result["Shiftr"] == []


def test_build_partner_exports_does_not_duplicate_leads():
    lead = make_lead(
        route="Shiftr",
        company="Multi Route Corp",
        signal="technology project",
        evidence=(
            "Multi Route Corp has a technology project."
        ),
        approved_routes=["Shiftr"],
    )

    lead["potential_routes"] = [
        "Shiftr",
        "Paxus",
    ]

    result = build_partner_exports([lead])

    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 0
    assert result["Shiftr"][0]["company"] == "Multi Route Corp"


def test_build_partner_exports_handles_empty_input():
    result = build_partner_exports([])

    assert result["Thorio"] == []
    assert result["Shiftr"] == []
    assert result["Paxus"] == []


def test_unsupported_route_is_not_exported():
    lead = make_lead(
        route="UnknownPartner",
        company="Unknown Corp",
        signal="remote software engineer",
        evidence=(
            "Unknown Corp is hiring a remote software engineer."
        ),
    )

    result = build_partner_exports([lead])

    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert result["Thorio"] == []
