from lead_engine.delivery_manifest import build_delivery_manifest


def make_lead(
    route,
    signal,
    evidence,
    score=50,
):
    return {
        "source": "linkedin",
        "source_id": f"quality-{route.lower()}",
        "url": "https://example.com/job/quality-test",
        "company": "QualityTestCo",
        "person": "Jane Smith",
        "contact_name": "Jane Smith",
        "contact_title": "CTO",
        "contact_email": "jane@example.com",
        "signal": signal,
        "evidence": evidence,
        "route": route,
        "potential_routes": [route],
        "lead_score": score,
        "priority": "High",
        "status": "new",
    }


def test_high_quality_leads_are_delivered_to_correct_partners():
    leads = [
        make_lead(
            route="Shiftr",
            signal="software engineer",
            evidence="Company needs a software engineer.",
        ),
        make_lead(
            route="Paxus",
            signal="technology staffing",
            evidence="Company needs technology staffing.",
        ),
        make_lead(
            route="Thorio",
            signal="remote software engineer",
            evidence="Company is hiring a remote software engineer.",
        ),
    ]

    manifest = build_delivery_manifest(leads)

    assert manifest["counts"] == {
        "Shiftr": 1,
        "Paxus": 1,
        "Thorio": 1,
        "Review": 0,
    }

    assert manifest["Shiftr"][0]["delivery_status"] == "approved"
    assert manifest["Paxus"][0]["delivery_status"] == "approved"
    assert manifest["Thorio"][0]["delivery_status"] == "approved"


def test_low_score_lead_is_blocked_from_partner_delivery():
    lead = make_lead(
        route="Shiftr",
        signal="software engineer",
        evidence="Company needs a software engineer.",
        score=49,
    )

    manifest = build_delivery_manifest([lead])

    assert manifest["Shiftr"] == []
    assert len(manifest["Review"]) == 1
    assert manifest["Review"][0]["delivery_status"] == "review"
    assert manifest["Review"][0]["delivery_reason"] == "delivery_policy_rejected"


def test_route_mismatch_is_blocked_even_with_high_score():
    lead = make_lead(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
        score=100,
    )

    manifest = build_delivery_manifest([lead])

    assert manifest["Shiftr"] == []
    assert len(manifest["Review"]) == 1
    assert manifest["Review"][0]["delivery_status"] == "review"
    assert manifest["Review"][0]["delivery_reason"] == "route_evidence_mismatch"
