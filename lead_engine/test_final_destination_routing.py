from .lead_routes import route_leads, route_state


def test_paxus_base_match_waits_for_true_referral():
    lead = {
        "fingerprint": "paxus-gate",
        "potential_routes": ["Shiftr", "Paxus", "Thorio"],
        "qualification_results": {"Paxus": {"qualified": True, "true_referral": False}},
    }
    routed = route_leads([lead])
    assert len(routed["Shiftr"]) == 1
    assert len(routed["Thorio"]) == 1
    assert routed["Paxus"] == []
    assert routed["Review"] == []
    state = route_state(lead)
    assert state["destinations"]["Paxus"]["state"] == "paxus_research_required"
    assert state["destinations"]["Paxus"]["final"] is False


def test_paxus_true_referral_reaches_human_action():
    lead = {
        "fingerprint": "paxus-ready",
        "potential_routes": ["Paxus"],
        "qualification_results": {"Paxus": {"qualified": True, "true_referral": True}},
    }
    routed = route_leads([lead])
    assert len(routed["Paxus"]) == 1
    assert routed["Review"] == []
    assert route_state(lead)["destinations"]["Paxus"]["state"] == "ready_for_human_action"
