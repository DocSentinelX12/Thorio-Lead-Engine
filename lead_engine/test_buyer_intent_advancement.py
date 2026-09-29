from .buyer_intent_advancement import build_buyer_intent_advancement


def test_advancement_requires_missing_evidence_before_normal_progression():
    progression = {
        "current_state": "problem_acknowledged",
        "history": [
            {
                "current_state": "problem_acknowledged",
                "evidence_ref": "evt-problem",
                "evidence_text": "We have an engineering capacity problem.",
                "event_index": 0,
            }
        ],
        "known_qualification": {"active_need": {"value": "engineering capacity"}},
        "missing_qualification": {
            "dimension": "business_impact",
            "required": True,
        },
        "next_best_action": "clarify_business_impact",
        "next_best_question": "What business consequence matters most?",
    }
    result = build_buyer_intent_advancement(progression, buying_signal={"category": "general_engagement"})
    assert result["advance_allowed"] is False
    assert result["missing_evidence"] == ["business_impact"]
    assert result["mode"] == "clarify_impact"
    assert result["stage_evidence"]["evidence_ref"] == "evt-problem"


def test_advancement_recognizes_explicit_evaluation_without_treating_it_as_commitment():
    progression = {
        "current_state": "evaluation",
        "history": [
            {
                "current_state": "evaluation",
                "evidence_ref": "evt-eval",
                "evidence_text": "We are comparing providers.",
                "event_index": 2,
            }
        ],
        "known_qualification": {
            "active_need": {"value": "engineering capacity"},
            "business_impact": {"value": "release delays"},
        },
        "missing_qualification": {
            "dimension": "decision_process",
            "required": True,
        },
        "next_best_action": "map_evaluation_process",
        "next_best_question": "What criteria and approval steps determine the decision?",
    }
    result = build_buyer_intent_advancement(
        progression,
        buying_signal={"category": "active_evaluation", "do_not_overstate": True},
    )
    assert result["advance_allowed"] is False
    assert result["mode"] == "map_decision"
    assert result["buyer_signal_category"] == "active_evaluation"
    assert result["commitment_claim_allowed"] is False


def test_advancement_requires_execution_details_after_explicit_commitment():
    progression = {
        "current_state": "commercial_commitment",
        "history": [
            {
                "current_state": "commercial_commitment",
                "evidence_ref": "evt-commit",
                "evidence_text": "Send the agreement.",
                "event_index": 3,
            }
        ],
        "known_qualification": {},
        "missing_qualification": {
            "dimension": "commitment_details",
            "required": True,
        },
        "next_best_action": "confirm_commitment_details",
        "next_best_question": "What specific next step should we put in motion?",
    }
    result = build_buyer_intent_advancement(
        progression,
        buying_signal={"category": "explicit_commitment", "do_not_overstate": False},
    )
    assert result["advance_allowed"] is False
    assert "execution details" in result["blocked_reason"]
    assert result["mode"] == "confirm_execution"


def test_advancement_allows_evidence_bounded_discovery_after_no_need_statement():
    progression = {
        "current_state": "no_need",
        "history": [
            {
                "current_state": "no_need",
                "evidence_ref": "evt-no-need",
                "evidence_text": "We do not need this.",
                "event_index": 4,
            }
        ],
        "known_qualification": {},
        "missing_qualification": {
            "dimension": "no_need_reason",
            "required": True,
        },
        "next_best_action": "diagnose_no_need",
        "next_best_question": "What specifically makes this unnecessary right now?",
    }
    result = build_buyer_intent_advancement(
        progression,
        buying_signal={"category": "general_engagement", "do_not_overstate": True},
    )
    assert result["advance_allowed"] is False
    assert result["mode"] == "resolve_interruption"
    assert result["allowed_persuasion"] == "evidence_bounded_discovery"
    assert result["next_best_action"] == "diagnose_no_need"


def test_advancement_stops_on_terminal_rejection():
    progression = {
        "current_state": "rejected",
        "history": [
            {
                "current_state": "rejected",
                "evidence_ref": "evt-no",
                "evidence_text": "We do not need this.",
                "event_index": 4,
            }
        ],
        "known_qualification": {},
        "missing_qualification": {"dimension": "none", "required": False},
        "next_best_action": "stop_outreach",
        "next_best_question": "",
    }
    result = build_buyer_intent_advancement(progression)
    assert result["advance_allowed"] is False
    assert result["mode"] == "stop"
    assert result["allowed_persuasion"] == "none"


def test_reengagement_advancement_ignores_stale_historical_qualification():
    from .buyer_intent_advancement import build_buyer_intent_advancement

    progression = {
        "current_state": "evaluation",
        "known_qualification": {
            "decision_process": {
                "value": "CTO approval",
                "evidence_ref": "evt-old",
                "event_index": 0,
            },
            "timing": {
                "value": "next quarter",
                "evidence_ref": "evt-old",
                "event_index": 0,
            },
        },
        "active_qualification": {},
        "missing_qualification": {
            "dimension": "decision_process",
            "required": True,
        },
        "next_best_action": "map_evaluation_process",
        "next_best_question": "What criteria, people, and approval steps will determine whether you move forward?",
        "history": [
            {
                "current_state": "evaluation",
                "evidence_ref": "evt-new-eval",
                "evidence_text": "We are comparing providers again.",
                "event_index": 2,
            }
        ],
        "reengagement_reconciliation": {
            "status": "reopened",
            "prior_state": "evaluation",
            "evidence_ref": "evt-reengage",
        },
    }

    result = build_buyer_intent_advancement(progression)
    assert result["advance_allowed"] is False
    assert result["missing_evidence"] == ["decision_process"]
    assert result["known_qualification"] == {}
