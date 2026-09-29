from .next_evidence_intelligence import build_next_evidence_plan


def _lead(**overrides):
    value = {
        "opportunity_id": "opp-1",
        "research_gaps": {
            "missing_sections": [
                "current_intent_research",
                "route_research",
                "commercial_research",
            ]
        },
        "eligible_routes": ["Thorio", "Shiftr"],
    }
    value.update(overrides)
    return value


def test_next_evidence_plan_only_targets_missing_sections():
    result = build_next_evidence_plan(_lead())
    assert result["missing_sections"] == [
        "current_intent_research",
        "route_research",
        "commercial_research",
    ]
    assert result["target_count"] == 3
    assert all(item["research_section"] in result["missing_sections"] for item in result["targets"])


def test_next_evidence_plan_keeps_route_evidence_independent():
    result = build_next_evidence_plan(_lead())
    route = next(item for item in result["targets"] if item["research_section"] == "route_research")
    assert {item["route"] for item in route["route_targets"]} == {"Thorio", "Shiftr"}
    assert all(item["evidence_to_find"] for item in route["route_targets"])


def test_next_evidence_plan_never_converts_targets_to_evidence():
    result = build_next_evidence_plan(_lead())
    assert all("evidence" not in item for item in result["targets"])
    assert "not evidence" in result["interpretation_note"]


def test_next_evidence_plan_derives_missing_sections_when_gaps_are_absent():
    result = build_next_evidence_plan({
        "opportunity_id": "opp-2",
        "business_need_research": {"evidence": [{"url": "https://example.com/need"}]},
        "current_intent_research": {"evidence": []},
    })
    assert result["missing_sections"] == [
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
    ]
