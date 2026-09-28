from .sales_closer_intelligence import build_commercial_strategy


def _lead(events):
    return {
        "company": "Acme",
        "conversation_events": events,
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "engineering capacity",
            "evidence_url": "https://example.com/need",
        },
    }


def test_commercial_strategy_exposes_evidence_grounded_advancement_guard():
    strategy = build_commercial_strategy(
        _lead(
            [
                {
                    "outcome": "replied",
                    "text": "We have an engineering capacity problem.",
                    "evidence_ref": "evt-problem",
                }
            ]
        )
    )
    advancement = strategy["buyer_intent_progression"]["advancement"]
    assert advancement["current_state"] == "problem_acknowledged"
    assert advancement["advance_allowed"] is False
    assert advancement["missing_evidence"] == ["business_impact"]
    assert advancement["stage_evidence"]["evidence_ref"] == "evt-problem"
    assert advancement["allowed_persuasion"] == "evidence_bounded_discovery"


def test_commercial_strategy_keeps_evaluation_distinct_from_commitment():
    strategy = build_commercial_strategy(
        _lead(
            [
                {
                    "outcome": "replied",
                    "text": "We are comparing providers and reviewing proposals.",
                    "evidence_ref": "evt-eval",
                }
            ]
        )
    )
    advancement = strategy["buyer_intent_advancement"]
    assert advancement["current_state"] == "evaluation"
    assert advancement["buyer_signal_category"] == "active_evaluation"
    assert advancement["commitment_claim_allowed"] is False
    assert advancement["mode"] == "map_decision"


def test_commercial_strategy_requires_execution_details_after_commitment():
    strategy = build_commercial_strategy(
        _lead(
            [
                {
                    "outcome": "replied",
                    "text": "Send the agreement and kickoff options.",
                    "evidence_ref": "evt-commit",
                }
            ]
        )
    )
    advancement = strategy["buyer_intent_advancement"]
    assert advancement["current_state"] == "commercial_commitment"
    assert advancement["advance_allowed"] is False
    assert "execution details" in advancement["blocked_reason"]


def test_commercial_strategy_stops_advancement_after_explicit_rejection():
    strategy = build_commercial_strategy(
        _lead(
            [
                {
                    "outcome": "replied",
                    "text": "We do not need this.",
                    "evidence_ref": "evt-reject",
                }
            ]
        )
    )
    advancement = strategy["buyer_intent_advancement"]
    assert advancement["current_state"] == "no_need"
    assert advancement["advance_allowed"] is False
    assert advancement["allowed_persuasion"] == "none"
