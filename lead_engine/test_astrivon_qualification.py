from .qualification import evaluate_company_qualification


def test_astrivon_qualifies_from_verified_need_and_route_research():
    lead = {
        "company": "Acme",
        "signal": "Looking for a dev agency",
        "evidence": "Startup needs an MVP built for its platform.",
        "company_research": {
            "company_verified": True,
        },
        "business_need_research": {
            "verified": True,
            "business_need": "Need an MVP built for the startup",
        },
        "current_intent_research": {
            "verified": True,
            "current_need": "Looking for a dev agency now",
            "observed_at": "2026-09-26T10:00:00+00:00",
        },
        "technical_product_hiring_research": {
            "verified": True,
            "requirement": "MVP product development",
        },
        "commercial_research": {
            "verified": True,
            "description": "Startup evaluating an external technology partner",
        },
        "route_research": {
            "verified": True,
            "routes": {
                "Astrivon Labs": {
                    "verified": True,
                    "evidence": "Startup needs an MVP built and is looking for a dev agency.",
                }
            },
        },
    }

    result = evaluate_company_qualification(lead)
    astrivon = result["companies"]["Astrivon Labs"]

    assert astrivon["qualified"] is True
    assert "Astrivon Labs" in result["qualified_companies"]
