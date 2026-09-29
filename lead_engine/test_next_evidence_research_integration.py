from .research_package import build_canonical_research_package, finalize_research_readiness


def test_canonical_research_package_materializes_next_evidence_targets():
    lead = {
        "opportunity_id": "opp-next-evidence",
        "fingerprint": "opp-next-evidence",
        "company": "Acme",
        "eligible_routes": ["Thorio", "Shiftr"],
    }
    package = build_canonical_research_package(lead, {})
    plan = package["research_gaps"]["next_evidence_to_find"]
    assert plan["opportunity_id"] == "opp-next-evidence"
    assert plan["target_count"] == 5
    assert {item["research_section"] for item in plan["targets"]} == {
        "business_need_research",
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
    }


def test_finalize_research_readiness_refreshes_next_evidence_targets():
    lead = {
        "opportunity_id": "opp-refresh",
        "fingerprint": "opp-refresh",
        "company": "Acme",
        "research_gaps": {
            "missing_sections": ["commercial_research"],
        },
        "business_need_research": {"evidence": [{"url": "https://example.com/need", "evidence": "Observed need"}]},
    }
    updated, readiness = finalize_research_readiness(lead)
    assert readiness["ready"] is False
    plan = updated["research_gaps"]["next_evidence_to_find"]
    assert plan["missing_sections"] == [
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
    ]
    assert plan["target_count"] == 4
