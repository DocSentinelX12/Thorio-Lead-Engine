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
    value = lead(); value["company_research"]["decision_maker_verification_status"] = "observed_needs_role_verification"
    with pytest.raises(OutreachContractError): build_outreach_decision(value)


def test_decline_and_opt_out_are_terminal():
    declined = apply_outcome(lead(), "declined"); opted_out = apply_outcome(lead(), "opted_out")
    assert declined["next_follow_up_at"] is None and opted_out["next_follow_up_at"] is None
    assert declined["outreach_stop_reason"] == "declined" and opted_out["outreach_stop_reason"] == "opted_out"


def test_no_response_advances_cadence_and_exhausts():
    value = lead(outreach_attempt=0); updated = apply_outcome(value, "no_response", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert updated["outreach_state"] == "ready" and updated["outreach_attempt"] == 1 and updated["next_follow_up_at"] is not None
    value = lead(outreach_attempt=3); exhausted = apply_outcome(value, "no_response", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert exhausted["outreach_state"] == "exhausted" and exhausted["next_follow_up_at"] is None


def test_objection_handler_stops_on_opt_out_language(): assert "not follow up" in objection_response("Please stop and remove me", "Thorio").lower()
def test_objection_handler_does_not_make_unsupported_price_claims(): assert "assumptions" in objection_response("That sounds too expensive", "Shiftr").lower()


def test_astrivon_outreach_requests_introductory_meeting():
    lead = lead(
        potential_routes=["Astrivon Labs"],
        qualification_results={
            "Astrivon Labs": {
                "qualified": True,
                "route_research": {
                    "verified": True,
                    "evidence": "Verified Astrivon route need.",
                },
            }
        },
    )
    lead["research_status"] = "complete"
    lead["research_verified_fields"] = [
        "current_intent_research",
        "business_need_research",
    ]
    lead["current_intent_research"] = {
        "verified": True,
        "current_need": "Looking for a dev agency",
        "evidence_url": "https://example.com/need",
    }
    lead["business_need_research"] = {
        "verified": True,
        "business_need": "Need an MVP built",
        "evidence_url": "https://example.com/mvp",
    }
    decision = build_outreach_decision(lead)
    assert decision.route == "Astrivon Labs"
    assert "introductory meeting" in decision.body
