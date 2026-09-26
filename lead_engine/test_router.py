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


def test_all_documented_astrivon_core_signals_route_to_astrivon():
    signals = [
        ("Looking for a dev agency", "Need a dev agency."),
        ("Looking for a tech partner", "Need a technology partner."),
        ("Need an MVP built for my startup", "Startup needs an MVP."),
        ("Looking for a B2B outreach expert", "Need B2B outreach."),
        ("Looking for a B2B sales representative", "Need B2B sales."),
        ("Hiring lead generation specialist", "Need lead generation."),
        ("Hiring sales automation expert", "Need sales automation."),
        ("Hiring AI/ML developer", "Need an AI/ML developer."),
        ("Hiring Computer Vision specialist", "Need computer vision."),
        ("Looking to automate business workflow / CRM", "Need CRM automation."),
        ("Hiring full-stack software engineer", "Need a full-stack software engineer."),
        ("Need help scaling my web/mobile app", "Need help scaling the web/mobile app."),
        ("Startup just raised seed funding", "The startup raised seed funding."),
        ("Founder is non-technical", "The founder is a non-technical founder."),
        ("Looking to outsource sales pipeline", "Need to outsource the sales pipeline."),
        ("Need to reduce in-house dev costs", "Need to reduce in-house dev costs."),
        ("Need to reduce in-house sales costs", "Need to reduce in-house sales costs."),
    ]
    for signal, evidence in signals:
        assert "Astrivon Labs" in potential_routes("Example Startup", signal, evidence), (signal, evidence)
