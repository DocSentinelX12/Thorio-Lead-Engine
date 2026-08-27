from lead_engine.delivery_manifest import build_delivery_manifest


def make_lead(
    route,
    signal,
    evidence,
    score=100,
):
    return {
        "source": "linkedin",
        "source_id": f"routing-{route.lower()}",
        "url": "https://example.com/job/routing-test",
        "company": "RoutingTestCo",
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
        "delivery_status": "approved",
        "delivery_reason": "",
    }


def test_shiftr_technical_lead_is_delivered():
    lead = make_lead(
        route="Shiftr",
        signal="software engineer",
        evidence="Company needs a software engineer.",
    )

    manifest = build_delivery_manifest([lead])

    assert len(manifest["Shiftr"]) == 1
    assert manifest["Review"] == []


def test_shiftr_office_manager_is_reviewed():
    lead = make_lead(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
    )

    manifest = build_delivery_manifest([lead])

    assert manifest["Shiftr"] == []
    assert len(manifest["Review"]) == 1
    assert manifest["Review"][0]["delivery_reason"] == (
        "route_evidence_mismatch"
    )


def test_high_score_cannot_override_route_mismatch():
    lead = make_lead(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
        score=100,
    )

    manifest = build_delivery_manifest([lead])

    assert manifest["Shiftr"] == []
    assert len(manifest["Review"]) == 1


def test_company_name_cannot_create_route_match():
    lead = make_lead(
        route="Shiftr",
        signal="office manager",
        evidence="Company is hiring an office manager.",
    )

    lead["company"] = "QualityTestCo"

    manifest = build_delivery_manifest([lead])

    assert manifest["Shiftr"] == []
    assert len(manifest["Review"]) == 1


def test_thorio_remote_product_lead_is_delivered():
    lead = make_lead(
        route="Thorio",
        signal="remote product designer",
        evidence="Company is hiring a remote product designer.",
    )

    manifest = build_delivery_manifest([lead])

    assert len(manifest["Thorio"]) == 1
    assert manifest["Review"] == []


def test_paxus_contract_staffing_lead_is_delivered():
    lead = make_lead(
        route="Paxus",
        signal="contract staffing",
        evidence="Company needs contract staffing.",
    )

    manifest = build_delivery_manifest([lead])

    assert len(manifest["Paxus"]) == 1
    assert manifest["Review"] == []


def test_unsupported_route_goes_to_review():
    lead = make_lead(
        route="Unknown",
        signal="software engineer",
        evidence="Company needs a software engineer.",
    )

    manifest = build_delivery_manifest([lead])

    assert manifest["Shiftr"] == []
    assert manifest["Paxus"] == []
    assert manifest["Thorio"] == []
    assert len(manifest["Review"]) == 1
    assert manifest["Review"][0]["delivery_reason"] == (
        "unsupported_route"
    )


def test_manifest_counts_match_queues():
    leads = [
        make_lead(
            route="Shiftr",
            signal="software engineer",
            evidence="Company needs a software engineer.",
        ),
        make_lead(
            route="Paxus",
            signal="contract staffing",
            evidence="Company needs contract staffing.",
        ),
        make_lead(
            route="Thorio",
            signal="remote product designer",
            evidence="Company needs a remote product designer.",
        ),
        make_lead(
            route="Shiftr",
            signal="office manager",
            evidence="Company is hiring an office manager.",
        ),
    ]

    manifest = build_delivery_manifest(leads)

    assert manifest["counts"]["Shiftr"] == len(manifest["Shiftr"])
    assert manifest["counts"]["Paxus"] == len(manifest["Paxus"])
    assert manifest["counts"]["Thorio"] == len(manifest["Thorio"])
    assert manifest["counts"]["Review"] == len(manifest["Review"])
