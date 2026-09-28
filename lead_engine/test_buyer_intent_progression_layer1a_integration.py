from .buyer_intent_progression import build_buyer_intent_progression


def _event(text, ref):
    return {"outcome": "replied", "text": text, "evidence_ref": ref}


def test_layer1a_contradiction_replaces_stale_evaluation_and_preserves_history():
    result = build_buyer_intent_progression({"conversation_events": [_event("We are comparing providers.", "evt-eval"), _event("We are no longer evaluating providers. We are just gathering information.", "evt-clarify")]})
    assert result["current_state"] == "engaged"
    assert result["history"][0]["current_state"] == "evaluation"
    assert result["history"][1]["prior_state"] == "evaluation"
    assert result["history"][1]["current_state"] == "engaged"
    assert result["history"][1]["transition_type"] == "contradicted"
    assert result["active_state_supersession"]["status"] == "superseded"
    assert result["active_state_supersession"]["prior_state"] == "evaluation"
    assert result["active_state_supersession"]["active_state"] == "engaged"
    assert result["active_state_supersession"]["evidence_ref"] == "evt-clarify"


def test_layer1a_lower_ranked_non_contradictory_evidence_does_not_regress_state():
    result = build_buyer_intent_progression({"conversation_events": [_event("We are comparing providers.", "evt-eval"), _event("We have a problem with engineering capacity.", "evt-problem")]})
    assert result["current_state"] == "evaluation"
    assert result["active_state_supersession"]["status"] == "none"


def test_layer1a_contradiction_can_replace_problem_with_no_need_and_preserve_evidence():
    result = build_buyer_intent_progression({"conversation_events": [_event("We have an engineering capacity problem.", "evt-problem"), _event("The problem is resolved now.", "evt-resolved")]})
    assert result["current_state"] == "no_need"
    assert result["history"][0]["current_state"] == "problem_acknowledged"
    assert result["history"][1]["transition_type"] == "contradicted"
    assert result["active_state_supersession"]["prior_state"] == "problem_acknowledged"
    assert result["active_state_supersession"]["active_state"] == "no_need"


def test_layer1a_closer_integration_uses_active_state_without_inventing_progression():
    from .sales_closer_intelligence import build_commercial_strategy
    strategy = build_commercial_strategy({"conversation_events": [_event("We are comparing providers.", "evt-eval"), _event("We are no longer evaluating providers. We are just gathering information.", "evt-clarify")], "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "engineering capacity", "evidence_url": "https://example.com/need"}})
    progression = strategy["buyer_intent_progression"]
    assert progression["current_state"] == "engaged"
    assert progression["active_state_supersession"]["prior_state"] == "evaluation"
    assert strategy["conversation_intelligence"]["buyer_intent_state"] == "engaged"
    assert strategy["conversation_intelligence"]["next_best_action"] == "clarify_business_impact"


def test_layer1a_outreach_uses_current_engaged_strategy_after_contradiction():
    from .outreach_engine import build_outreach_decision
    lead = {"conversation_events": [_event("We are comparing providers.", "evt-eval"), _event("We are no longer evaluating providers. We are just gathering information.", "evt-clarify")], "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "engineering capacity", "evidence_url": "https://example.com/need"}}
    decision = build_outreach_decision(lead)
    strategy = decision.commercial_strategy
    assert strategy["buyer_intent_progression"]["current_state"] == "engaged"
    assert strategy["buyer_intent_progression"]["active_state_supersession"]["prior_state"] == "evaluation"
    assert strategy["conversation_intelligence"]["next_best_action"] == "discover_business_outcome"
    assert strategy["conversation_intelligence"]["next_best_question"] in decision.body
