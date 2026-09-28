from datetime import datetime, timezone

import pytest

from .outreach_engine import OutreachContractError, apply_outcome, build_outreach_decision, objection_response, choose_route


def lead(**overrides):
    value = {"fingerprint": "o1", "company": "Acme", "potential_routes": ["Thorio", "Shiftr"], "signal": "UNTRUSTED DISCOVERY TEXT THAT MUST NOT DRIVE OUTREACH", "research_status": "complete", "research_verified_fields": ["current_intent_research"], "company_research": {"company_verified": True, "decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_verification_status": "verified", "decision_maker_email": "taylor@example.com"}, "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "verified need from research", "evidence_url": "https://example.com/researched-need"}, "qualification_results": {"Thorio": {"qualified": True, "route_research": {"verified": True, "evidence": "Verified Thorio route."}}, "Shiftr": {"qualified": True, "route_research": {"verified": True, "evidence": "Verified Shiftr route."}}}, "evidence_events": [{"source_url": "https://example.com/signal"}]}
    value.update(overrides)
    return value


def test_decision_uses_verified_research_not_raw_signal():
    decision = build_outreach_decision(lead(), now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert decision.route == "Thorio"
    assert decision.contact_name == "Taylor"
    assert "verified need from research" in decision.body
    assert "UNTRUSTED DISCOVERY TEXT" not in decision.body
    assert "https://example.com/taylor" in decision.evidence_refs
    assert "https://example.com/researched-need" in decision.evidence_refs
    assert decision.next_state == "drafted"


def test_paxus_wins_route_selection_only_when_true_referral_is_verified():
    value = lead(potential_routes=["Thorio", "Paxus"], qualification_results={"Paxus": {"qualified": True, "true_referral": True, "route_research": {"verified": True, "evidence": "Verified Paxus route."}}, "Thorio": {"qualified": False, "route_research": {"verified": True, "evidence": "Verified Thorio route."}}})
    assert choose_route(value) == "Paxus"
    value["qualification_results"] = {"Paxus": {"qualified": True, "true_referral": False, "route_research": {"verified": True, "evidence": "Verified Paxus route."}}, "Thorio": {"qualified": True, "route_research": {"verified": True, "evidence": "Verified Thorio route."}}}
    assert choose_route(value) == "Thorio"


def test_missing_researched_need_blocks_outreach_even_when_raw_signal_exists():
    value = lead(current_intent_research={}, research_verified_fields=[])
    with pytest.raises(OutreachContractError): build_outreach_decision(value)


def test_missing_evidence_blocks_outreach():
    value = lead(signal="")
    value["current_intent_research"] = {"verified": True, "verification_status": "verified", "current_need": "verified need"}
    value["evidence_events"] = []
    with pytest.raises(OutreachContractError): build_outreach_decision(value)


def test_no_decision_maker_evidence_blocks_outreach():
    value = lead(company_research={"company_verified": True, "decision_maker": "Taylor", "decision_maker_verification_status": "verified"})
    with pytest.raises(OutreachContractError): build_outreach_decision(value)


def test_unverified_company_blocks_outreach():
    value = lead(company_research={"decision_maker": "Taylor", "decision_maker_evidence": "https://example.com/taylor", "decision_maker_verification_status": "verified", "decision_maker_email": "taylor@example.com"})
    with pytest.raises(OutreachContractError): build_outreach_decision(value)


def test_unverified_decision_maker_blocks_outreach():
    value = lead()
    value["company_research"]["decision_maker_verification_status"] = "observed_needs_role_verification"
    with pytest.raises(OutreachContractError): build_outreach_decision(value)


def test_decline_and_opt_out_are_terminal():
    declined = apply_outcome(lead(), "declined")
    opted_out = apply_outcome(lead(), "opted_out")
    assert declined["next_follow_up_at"] is None and opted_out["next_follow_up_at"] is None
    assert declined["outreach_stop_reason"] == "declined" and opted_out["outreach_stop_reason"] == "opted_out"


def test_no_response_advances_cadence_and_exhausts():
    value = lead(outreach_attempt=0)
    updated = apply_outcome(value, "no_response", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert updated["outreach_state"] == "ready" and updated["outreach_attempt"] == 1 and updated["next_follow_up_at"] is not None
    value = lead(outreach_attempt=3)
    exhausted = apply_outcome(value, "no_response", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert exhausted["outreach_state"] == "exhausted" and exhausted["next_follow_up_at"] is None


def test_objection_handler_stops_on_opt_out_language():
    assert "not follow up" in objection_response("Please stop and remove me", "Thorio").lower()


def test_objection_handler_does_not_make_unsupported_price_claims():
    assert "assumptions" in objection_response("That sounds too expensive", "Shiftr").lower()


def test_closer_strategy_distinguishes_verified_fact_from_inference_and_unknown():
    decision = build_outreach_decision(
        lead(
            business_need_research={
                "verified": True,
                "verification_status": "verified",
                "business_need": "Expand engineering capacity",
                "evidence_url": "https://example.com/business-need",
            },
            research_verified_fields=["current_intent_research", "business_need_research"],
        )
    )
    assert decision.commercial_strategy["verified_facts"]
    assert decision.commercial_strategy["value_hypotheses"]
    assert decision.commercial_strategy["unknowns"]
    assert decision.commercial_strategy["psychological_objective"] == "diagnose"


def test_closer_strategy_uses_conversation_state_for_interested_prospect():
    value = lead(
        revenue_lifecycle_state="conversation_active",
        outreach_state="interested",
        conversation_events=[{"outcome": "interested", "text": "This is interesting. What would the process look like?"}],
    )
    decision = build_outreach_decision(value)
    assert decision.commercial_strategy["conversation_state"] == "interested"
    assert decision.commercial_strategy["psychological_objective"] == "clarify_value"
    assert decision.commercial_strategy["next_best_action"] == "answer_and_advance"


def test_objection_handler_uses_objection_category_and_next_step():
    response = objection_response(
        "We already have an internal engineering team, so why would we need this?",
        "Shiftr",
    )
    lowered = response.lower()
    assert "capacity" in lowered or "gap" in lowered
    assert "question" in lowered


def test_closer_never_invents_urgency_when_research_has_no_timing_evidence():
    decision = build_outreach_decision(lead())
    assert decision.commercial_strategy["urgency_basis"] == "none_verified"
    assert "urgent" not in decision.body.lower()
    assert "deadline" not in decision.body.lower()


def test_closer_message_quality_gate_records_truthfulness_and_conversion_checks():
    decision = build_outreach_decision(lead())
    quality = decision.commercial_strategy["message_quality"]
    assert quality["passed"] is True
    assert quality["truthfulness"] is True
    assert quality["clear_next_step"] is True
    assert quality["unsupported_urgency"] is False


def test_build_outreach_decision_enforces_message_quality_gate(monkeypatch):
    from . import outreach_engine

    monkeypatch.setattr(
        outreach_engine,
        "_sales_body",
        lambda route, contact_name, company, signal, strategy: (
            f"Hi {contact_name},\\n\\nThis is urgent. Act now before the deadline."
        ),
    )
    with pytest.raises(OutreachContractError, match="commercial truthfulness gate"):
        build_outreach_decision(lead())


def test_build_outreach_decision_rejects_unsupported_outcome_claim(monkeypatch):
    from . import outreach_engine

    monkeypatch.setattr(
        outreach_engine,
        "_sales_body",
        lambda route, contact_name, company, signal, strategy: (
            f"Hi {contact_name},\\n\\nWe will increase revenue and guarantee the result.\\n\\nWould you be open to a brief conversation?"
        ),
    )
    with pytest.raises(OutreachContractError, match="commercial truthfulness gate"):
        build_outreach_decision(lead())


def test_closer_message_quality_gate_rejects_manufactured_urgency():
    from .sales_closer_intelligence import evaluate_closer_message

    strategy = {"urgency_basis": "none_verified"}
    quality = evaluate_closer_message(
        "This is urgent and you need to act now before the deadline.",
        strategy,
        "verified need",
    )
    assert quality["passed"] is False
    assert "unsupported_urgency" in quality["violations"]


def test_closer_message_uses_verified_business_impact_without_inventing_roi():
    decision = build_outreach_decision(
        lead(
            business_need_research={
                "verified": True,
                "verification_status": "verified",
                "business_need": "Expand engineering capacity",
                "evidence_url": "https://example.com/business-need",
            },
            business_impact_research={
                "verified": True,
                "verification_status": "verified",
                "business_impact": "delivery capacity is constrained during the current hiring cycle",
                "cost_of_inaction": "the current release schedule remains constrained",
                "evidence_url": "https://example.com/business-impact",
            },
            research_verified_fields=["current_intent_research", "business_need_research"],
        )
    )
    assert "delivery capacity is constrained during the current hiring cycle" in decision.body
    assert "the current release schedule remains constrained" in decision.body
    assert "guaranteed" not in decision.body.lower()
    assert "increase revenue" not in decision.body.lower()
    assert decision.commercial_strategy["verified_business_impact"]
    assert decision.commercial_strategy["verified_cost_of_inaction"]


def test_closer_message_never_uses_unverified_business_impact_as_fact():
    decision = build_outreach_decision(
        lead(
            business_impact_research={
                "verified": False,
                "verification_status": "needs_verification",
                "business_impact": "revenue will increase by 30 percent",
                "cost_of_inaction": "the company will lose customers",
                "evidence_url": "https://example.com/unverified-impact",
            }
        )
    )
    assert "revenue will increase by 30 percent" not in decision.body
    assert "the company will lose customers" not in decision.body
    assert "Business impact research exists but is not verified, so its impact cannot be used as fact." in decision.commercial_strategy["unknowns"]


def test_closer_message_uses_discovery_unknown_instead_of_fabricating_business_impact():
    decision = build_outreach_decision(lead())
    assert "The business impact of the verified need is not yet established." in decision.commercial_strategy["unknowns"]
    assert "What is the main outcome you would want to improve?" not in decision.body
    assert "business consequence" in decision.body.lower()
