from .buyer_intent_progression import build_buyer_intent_progression
from .objection_constraint_diagnosis import build_objection_constraint_diagnosis


def _progression(events):
    return build_buyer_intent_progression({"conversation_events": events})


def test_no_need_without_reason_remains_unconfirmed_and_selects_diagnostic_question():
    events = [
        {"outcome": "replied", "text": "We do not need this.", "evidence_ref": "evt-no-need"},
    ]
    result = build_objection_constraint_diagnosis(
        {"conversation_events": events},
        _progression(events),
    )
    assert result["interruption_type"] == "no_need"
    assert result["status"] == "unconfirmed"
    assert result["hypothesis"] == ""
    assert result["evidence_refs"] == ["evt-no-need"]
    assert result["next_best_action"] == "diagnose_no_need"
    assert result["next_best_question"] == "What specifically makes this unnecessary right now, and is there any gap in the current approach worth evaluating?"
    assert result["permitted_persuasion"] == "evidence_bounded_discovery"


def test_no_need_with_existing_team_is_only_a_hypothesis_until_buyer_confirms_it():
    events = [
        {
            "outcome": "replied",
            "text": "We do not need this because our internal engineering team handles it.",
            "evidence_ref": "evt-no-need-team",
        },
    ]
    result = build_objection_constraint_diagnosis(
        {"conversation_events": events},
        _progression(events),
    )
    assert result["interruption_type"] == "no_need"
    assert result["status"] == "hypothesis"
    assert result["hypothesis_type"] == "existing_solution"
    assert result["evidence_refs"] == ["evt-no-need-team"]
    assert result["next_best_action"] == "diagnose_capacity_gap"
    assert result["permitted_persuasion"] == "evidence_bounded_discovery"


def test_explicit_confirmation_changes_hypothesis_to_confirmed_without_inventing_facts():
    events = [
        {
            "outcome": "replied",
            "text": "We do not need this because our internal engineering team handles it.",
            "evidence_ref": "evt-no-need-team",
        },
        {
            "outcome": "replied",
            "text": "Yes, our internal team is sufficient. We do not have a capacity gap.",
            "underlying_concern_confirmation": "existing_solution",
            "evidence_ref": "evt-confirm",
        },
    ]
    result = build_objection_constraint_diagnosis(
        {"conversation_events": events},
        _progression(events),
    )
    assert result["status"] == "confirmed"
    assert result["confirmation_evidence_ref"] == "evt-confirm"
    assert result["hypothesis_type"] == "existing_solution"
    assert result["next_best_action"] == "diagnose_capacity_gap"
    assert result["evidence_refs"] == ["evt-no-need-team", "evt-confirm"]


def test_later_rejection_of_hypothesis_supersedes_it_and_preserves_evidence():
    events = [
        {
            "outcome": "replied",
            "text": "We do not need this because our internal engineering team handles it.",
            "evidence_ref": "evt-no-need-team",
        },
        {
            "outcome": "replied",
            "text": "Actually, our internal team is not the reason. The timing is the issue.",
            "underlying_concern_rejection": "existing_solution",
            "underlying_concern_replacement": "timing",
            "evidence_ref": "evt-timing",
        },
    ]
    result = build_objection_constraint_diagnosis(
        {"conversation_events": events},
        _progression(events),
    )
    assert result["status"] == "superseded"
    assert result["state_transition"] == "superseded"
    assert result["state_evidence_ref"] == "evt-timing"
    assert result["evidence_refs"] == ["evt-no-need-team", "evt-timing"]
    assert result["hypothesis_type"] == "existing_solution"


def test_terminal_rejection_disables_diagnosis_persuasion():
    events = [
        {
            "outcome": "replied",
            "text": "No. We have decided not to pursue this. Please stop.",
            "evidence_ref": "evt-reject",
        },
    ]
    progression = {
        "current_state": "rejected",
        "history": [
            {
                "current_state": "rejected",
                "evidence_ref": "evt-reject",
                "evidence_text": "No. We have decided not to pursue this. Please stop.",
                "event_index": 0,
            }
        ],
    }
    result = build_objection_constraint_diagnosis(
        {"conversation_events": events},
        progression,
    )
    assert result["interruption_type"] == "rejected"
    assert result["status"] == "terminal"
    assert result["permitted_persuasion"] == "none"
    assert result["next_best_action"] == "stop_outreach"
    assert result["next_best_question"] == ""
