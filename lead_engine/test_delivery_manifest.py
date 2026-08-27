from lead_engine.delivery_manifest import (
    approved_partner_leads,
    build_delivery_manifest,
)


def make_lead(
    route="Shiftr",
    signal="remote software engineer",
    evidence="Company is hiring a remote software engineer.",
    company="Acme",
):
    return {
        "source": "linkedin",
        "source_id": "manifest-001",
        "url": "https://example.com/job/manifest-001",
        "company": company,
        "person": "Jane Smith",
        "contact_name": "Jane Smith",
        "contact_title": "CTO",
        "contact_email": "jane@example.com",
        "signal": signal,
        "evidence": evidence,
        "route": route,
        "potential_routes": [route],
        "lead_score": 8,
        "priority": "high",
        "status": "new",
    }


def test_manifest_routes_approved_leads():
    leads = [
        make_lead(
            route="Shiftr",
            signal="remote software engineer",
        ),
        make_lead(
            route="Paxus",
            signal="contract staffing recruiting",
        ),
        make_lead(
            route="Thorio",
            signal="remote product designer",
        ),
    ]

    manifest = build_delivery_manifest(leads)

    assert len(manifest["Shiftr"]) == 1
    assert len(manifest["Paxus"]) == 1
    assert len(manifest["Thorio"]) == 1
    assert len(manifest["Review"]) == 0

    assert manifest["counts"]["Shiftr"] == 1
    assert manifest["counts"]["Paxus"] == 1
    assert manifest["counts"]["Thorio"] == 1
    assert manifest["counts"]["Review"] == 0


def test_manifest_sends_invalid_lead_to_review():
    leads = [
        make_lead(
            route="Shiftr",
            signal="office manager",
            evidence="Company is hiring an office manager.",
        )
    ]

    manifest = build_delivery_manifest(leads)

    assert len(manifest["Shiftr"]) == 0
    assert len(manifest["Review"]) == 1
    assert manifest["Review"][0]["delivery_status"] == "review"
    assert manifest["Review"][0]["delivery_reason"] in {
        "route_evidence_mismatch",
        "delivery_policy_rejected",
    }


def test_manifest_rejects_unsupported_route():
    leads = [
        make_lead(
            route="UnknownPartner",
            signal="remote software engineer",
        )
    ]

    manifest = build_delivery_manifest(leads)

    assert len(manifest["Review"]) == 1
    assert manifest["counts"]["Review"] == 1
    assert manifest["Review"][0]["delivery_status"] == "review"


def test_approved_partner_leads_returns_only_partner_queue():
    leads = [
        make_lead(
            route="Shiftr",
            signal="software engineer",
        ),
        make_lead(
            route="Paxus",
            signal="contract staffing",
        ),
        make_lead(
            route="Thorio",
            signal="remote product designer",
        ),
    ]

    shiftr = approved_partner_leads(
        leads,
        "Shiftr",
    )

    assert len(shiftr) == 1
    assert shiftr[0]["route"] == "Shiftr"
    assert shiftr[0]["delivery_status"] == "approved"


def test_unsupported_partner_returns_empty_list():
    leads = [
        make_lead(
            route="Shiftr",
            signal="software engineer",
        )
    ]

    result = approved_partner_leads(
        leads,
        "NotAPartner",
    )

    assert result == []
