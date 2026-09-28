from .buyer_intent_progression import build_buyer_intent_progression


def event(text, outcome="replied", **fields):
    value = {"text": text, "outcome": outcome, "evidence_ref": fields.pop("evidence_ref", "evt")}
    value.update(fields)
    return value


def test_generic_engagement_does_not_advance_to_evaluation():
    result = build_buyer_intent_progression({"conversation_events": [event("Interesting, thanks for reaching out.")]})
    assert result["current_state"] == "engaged"
    assert result["history"][-1]["evidence_ref"] == "evt"


def test_problem_acknowledgment_accepts_specific_problem_phrase_without_inference():
    result = build_buyer_intent_progression({"conversation_events": [event("We have an engineering capacity problem.")]})
    assert result["current_state"] == "problem_acknowledged"
    assert result["missing_qualification"]["dimension"] == "business_impact"


def test_problem_acknowledgment_requires_explicit_problem_evidence():
    result = build_buyer_intent_progression({"conversation_events": [event("We have a problem with engineering capacity.")]})
    assert result["current_state"] == "problem_acknowledged"
    assert result["missing_qualification"]["dimension"] == "business_impact"


def test_impact_acknowledgment_requires_explicit_consequence():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We have a problem with engineering capacity.", evidence_ref="evt-problem"),
            event("It is causing delays for our releases.", evidence_ref="evt-impact"),
        ]}
    )
    assert result["current_state"] == "impact_acknowledged"
    assert result["transition"]["evidence_ref"] == "evt-impact"
    assert result["history"][0]["current_state"] == "problem_acknowledged"
    assert result["history"][1]["prior_state"] == "problem_acknowledged"


def test_evaluation_is_evidence_linked():
    result = build_buyer_intent_progression(
        {"conversation_events": [event("We are comparing providers and reviewing proposals.", evidence_ref="evt-eval")]}
    )
    assert result["current_state"] == "evaluation"
    assert result["transition"]["evidence_ref"] == "evt-eval"
    assert result["next_best_action"] == "map_evaluation_process"


def test_decision_process_does_not_assume_approval():
    result = build_buyer_intent_progression(
        {"conversation_events": [event("Our CTO and VP Engineering need to approve this.", evidence_ref="evt-decision")]}
    )
    assert result["current_state"] == "decision_process"
    assert result["known_qualification"]["authority_participants"]["evidence_ref"] == "evt-decision"
    assert result["next_best_action"] == "clarify_economic_criteria"


def test_commitment_requires_explicit_commercial_action():
    result = build_buyer_intent_progression(
        {"conversation_events": [event("Send the agreement and kickoff options.", evidence_ref="evt-commit")]}
    )
    assert result["current_state"] == "commercial_commitment"
    assert result["transition"]["evidence_ref"] == "evt-commit"
    assert result["next_best_action"] == "confirm_commitment_details"


def test_objection_interrupts_progression_without_deleting_history():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We are comparing providers.", evidence_ref="evt-eval"),
            event("We already have an internal engineering team.", outcome="objection", evidence_ref="evt-objection"),
        ]}
    )
    assert result["current_state"] == "existing_solution"
    assert len(result["history"]) == 2
    assert result["history"][0]["current_state"] == "evaluation"
    assert result["history"][1]["prior_state"] == "evaluation"
    assert result["next_best_action"] == "diagnose_capacity_gap"


def test_timing_delay_interrupts_without_manufacturing_urgency():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We are evaluating options.", evidence_ref="evt-eval"),
            event("Let's revisit next quarter.", outcome="timing", evidence_ref="evt-time"),
        ]}
    )
    assert result["current_state"] == "timing_delay"
    assert result["next_best_action"] == "map_timing_constraint"
    assert "urgent" not in result["transition"]["reason"].lower()


def test_rejection_is_terminal_until_explicit_reengagement():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We do not need this.", outcome="declined", evidence_ref="evt-reject"),
            event("I will think about it.", evidence_ref="evt-later"),
        ]}
    )
    assert result["current_state"] == "no_need"
    assert result["history"][0]["current_state"] == "no_need"


def test_explicit_reengagement_reopens_active_conversation_without_erasing_history():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We do not need this.", outcome="declined", evidence_ref="evt-reject"),
            event("Let's revisit this. Our situation changed.", outcome="re_engagement", evidence_ref="evt-reengage"),
        ]}
    )
    assert result["current_state"] == "re_engagement"
    assert result["history"][0]["current_state"] == "no_need"
    assert result["history"][1]["transition_type"] == "reengaged"


def test_opt_out_is_terminal():
    result = build_buyer_intent_progression(
        {"conversation_events": [event("Please unsubscribe me and stop contacting me.", outcome="opted_out", evidence_ref="evt-optout")]}
    )
    assert result["current_state"] == "rejected"
    assert result["transition"]["reason"] == "explicit opt-out"
    assert result["next_best_action"] == "stop_outreach"


def test_explicit_contradiction_supersedes_stale_evaluation_without_erasing_history():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We are comparing providers and reviewing proposals.", evidence_ref="evt-eval"),
            event("We are no longer evaluating providers. We are just gathering information.", evidence_ref="evt-clarify"),
        ]}
    )
    assert result["current_state"] == "engaged"
    assert result["history"][0]["current_state"] == "evaluation"
    assert result["history"][1]["prior_state"] == "evaluation"
    assert result["history"][1]["current_state"] == "engaged"
    assert result["history"][1]["transition_type"] == "contradicted"
    assert result["active_state_supersession"]["status"] == "superseded"
    assert result["active_state_supersession"]["prior_state"] == "evaluation"
    assert result["active_state_supersession"]["active_state"] == "engaged"
    assert result["active_state_supersession"]["evidence_ref"] == "evt-clarify"
    assert result["active_state_supersession"]["event_index"] == 1


def test_explicit_contradiction_can_supersede_problem_when_buyer_resolves_it():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We have an engineering capacity problem.", evidence_ref="evt-problem"),
            event("The problem is resolved now.", evidence_ref="evt-resolved"),
        ]}
    )
    assert result["current_state"] == "no_need"
    assert result["history"][0]["current_state"] == "problem_acknowledged"
    assert result["history"][1]["transition_type"] == "contradicted"
    assert result["active_state_supersession"]["prior_state"] == "problem_acknowledged"
    assert result["active_state_supersession"]["active_state"] == "no_need"


def test_non_contradictory_lower_ranked_event_does_not_replace_active_state():
    result = build_buyer_intent_progression(
        {"conversation_events": [
            event("We are comparing providers.", evidence_ref="evt-eval"),
            event("We have a problem with engineering capacity.", evidence_ref="evt-problem"),
        ]}
    )
    assert result["current_state"] == "evaluation"
    assert result["history"][-1]["current_state"] == "evaluation"
    assert result["active_state_supersession"]["status"] == "none"
