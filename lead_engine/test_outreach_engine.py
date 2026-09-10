from datetime import datetime, timezone

import pytest

from .outreach_engine import OutreachContractError, apply_outcome, build_outreach_decision, objection_response, choose_route


def lead(**overrides):
    value = {
        "fingerprint": "o1",
        "company": "Acme",
        "potential_routes": ["Thorio", "Shiftr"],
        "signal": "Acme needs a remote software engineer",
        "research_status": "complete",
        "company_research": {
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "contact_email": "taylor@example.com",
        },
        "evidence_events": [{"source_url": "https://example.com/signal"}],
    }
    value.update(overrides)
    return value


def test_decision_uses_verified_signal_and_contact_evidence():
    decision = build_outreach_decision(lead(), now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert decision.route == "Thorio"
    assert decision.contact_name == "Taylor"
    assert "Acme needs a remote software engineer" in decision.body
    assert decision.evidence_refs == ("https://example.com/signal", "https://example.com/taylor")
    assert decision.next_state == "drafted"


def test_paxus_wins_route_selection_only_when_true_referral_is_verified():
    value = lead(potential_routes=["Thorio", "Paxus"], qualification_results={"Paxus": {"true_referral": True}})
    assert choose_route(value) == "Paxus"
    value["qualification_results"] = {"Paxus": {"true_referral": False}}
    assert choose_route(value) == "Thorio"


def test_missing_evidence_blocks_outreach():
    value = lead(signal="")
    with pytest.raises(OutreachContractError):
        build_outreach_decision(value)


def test_no_decision_maker_evidence_blocks_outreach():
    value = lead(company_research={"decision_maker": "Taylor"})
    with pytest.raises(OutreachContractError):
        build_outreach_decision(value)


def test_decline_and_opt_out_are_terminal():
    declined = apply_outcome(lead(), "declined")
    opted_out = apply_outcome(lead(), "opted_out")
    assert declined["next_follow_up_at"] is None
    assert opted_out["next_follow_up_at"] is None
    assert declined["outreach_stop_reason"] == "declined"
    assert opted_out["outreach_stop_reason"] == "opted_out"


def test_no_response_advances_cadence_and_exhausts():
    value = lead(outreach_attempt=0)
    updated = apply_outcome(value, "no_response", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert updated["outreach_state"] == "ready"
    assert updated["outreach_attempt"] == 1
    assert updated["next_follow_up_at"] is not None
    value = lead(outreach_attempt=3)
    exhausted = apply_outcome(value, "no_response", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert exhausted["outreach_state"] == "exhausted"
    assert exhausted["next_follow_up_at"] is None


def test_objection_handler_stops_on_opt_out_language():
    assert "not follow up" in objection_response("Please stop and remove me", "Thorio").lower()


def test_objection_handler_does_not_make_unsupported_price_claims():
    response = objection_response("That sounds too expensive", "Shiftr")
    assert "guess" in response.lower()
