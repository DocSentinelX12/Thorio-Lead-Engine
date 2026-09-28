from .buyer_intent_progression import build_buyer_intent_progression
from .objection_constraint_diagnosis import build_objection_constraint_diagnosis
from .objection_resolution_intelligence import build_objection_resolution_intelligence


def test_resolved_concern_requires_post_resolution_buyer_evidence_before_progression_handoff():
    events = [
        {"outcome": "objection", "text": "The price is too high.", "evidence_ref": "evt-price"},
        {"outcome": "replied", "text": "We resolved the pricing concern.", "underlying_concern_resolution": "economic", "evidence_ref": "evt-resolved"},
    ]
    lead = {"conversation_events": events}
    diagnosis = build_objection_constraint_diagnosis(lead, build_buyer_intent_progression(lead))
    result = build_objection_resolution_intelligence(lead, diagnosis, build_buyer_intent_progression(lead))
    assert result["status"] == "resolved_pending_reconfirmation"
    assert result["progression_handoff_allowed"] is False
    assert result["next_best_action"] == "reconfirm_active_need"
    assert result["resolution_evidence_ref"] == "evt-resolved"


def test_explicit_post_resolution_evaluation_allows_progression_handoff():
    events = [
        {"outcome": "objection", "text": "The price is too high.", "evidence_ref": "evt-price"},
        {"outcome": "replied", "text": "We resolved the pricing concern.", "underlying_concern_resolution": "economic", "evidence_ref": "evt-resolved"},
        {"outcome": "replied", "text": "We are comparing providers now.", "evidence_ref": "evt-eval"},
    ]
    lead = {"conversation_events": events}
    progression = build_buyer_intent_progression(lead)
    diagnosis = build_objection_constraint_diagnosis(lead, progression)
    result = build_objection_resolution_intelligence(lead, diagnosis, progression)
    assert result["status"] == "resolved_and_reengaged"
    assert result["progression_handoff_allowed"] is True
    assert result["post_resolution_evidence_ref"] == "evt-eval"
    assert result["next_best_action"] == "map_evaluation_process"


def test_polite_acknowledgment_after_resolution_does_not_count_as_reengagement():
    events = [
        {"outcome": "objection", "text": "We need proof of delivery.", "evidence_ref": "evt-trust"},
        {"outcome": "replied", "text": "The delivery concern is resolved.", "underlying_concern_resolution": "trust", "evidence_ref": "evt-resolved"},
        {"outcome": "replied", "text": "Thanks, that is helpful.", "evidence_ref": "evt-polite"},
    ]
    lead = {"conversation_events": events}
    progression = build_buyer_intent_progression(lead)
    diagnosis = build_objection_constraint_diagnosis(lead, progression)
    result = build_objection_resolution_intelligence(lead, diagnosis, progression)
    assert result["status"] == "resolved_pending_reconfirmation"
    assert result["progression_handoff_allowed"] is False
    assert result["post_resolution_evidence_ref"] == ""


def test_reopened_concern_blocks_progression_handoff():
    events = [
        {"outcome": "objection", "text": "The price is too high.", "evidence_ref": "evt-price"},
        {"outcome": "replied", "text": "We resolved the pricing concern.", "underlying_concern_resolution": "economic", "evidence_ref": "evt-resolved"},
        {"outcome": "objection", "text": "Actually, price is still the issue.", "underlying_concern_confirmation": "economic", "evidence_ref": "evt-reopened"},
    ]
    lead = {"conversation_events": events}
    progression = build_buyer_intent_progression(lead)
    diagnosis = build_objection_constraint_diagnosis(lead, progression)
    result = build_objection_resolution_intelligence(lead, diagnosis, progression)
    assert result["status"] == "reopened"
    assert result["progression_handoff_allowed"] is False
    assert result["next_best_action"] == "clarify_economic_criteria"
