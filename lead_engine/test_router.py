from .router import potential_routes, route, score_routes


def test_score_routes_returns_all_destinations():
    scores = score_routes("ExampleCo", "office manager", "Hiring an office manager.")
    assert set(scores.keys()) == {"Shiftr", "Paxus", "Thorio", "Astrivon Labs"}


def test_astrivon_signal_is_scored_independently():
    scores = score_routes("Startup", "Looking for a dev agency", "Need an MVP built for my startup.")
    assert scores["Astrivon Labs"] > 0
    assert scores["Paxus"] == 0


def test_astrivon_workflow_automation_signal_routes_directly():
    assert "Astrivon Labs" in potential_routes("OperationsCo", "Looking to automate business workflow / CRM", "The company needs CRM automation.")


def test_existing_partner_routes_remain_independent():
    assert "Paxus" in potential_routes("RecruitCo", "technology recruitment", "Company needs technology recruitment support.")
    assert "Thorio" in potential_routes("RemoteTech", "remote product designer", "Company is hiring a remote product designer.")
    assert "Shiftr" in potential_routes("Acme", "software engineer hiring", "Acme is hiring a software engineer.")
