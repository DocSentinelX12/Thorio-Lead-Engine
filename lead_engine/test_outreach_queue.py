from lead_engine.outreach_queue import (
    build_outreach_queue,
    get_route_queue,
    summarize_queue,
)


def make_lead(
    route,
    score=10,
    qualified=True,
    duplicate=False,
):
    return {
        "company": "Example Corp",
        "route": route,
        "lead_score": score,
        "qualified": qualified,
        "possible_duplicate": duplicate,
    }


def test_routes_qualified_leads_to_shiftr():
    leads = [
        make_lead("Shiftr"),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Shiftr"]) == 1
    assert len(queues["Paxus"]) == 0
    assert len(queues["Thorio"]) == 0


def test_routes_qualified_leads_to_paxus():
    leads = [
        make_lead("Paxus"),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Paxus"]) == 1


def test_routes_qualified_leads_to_thorio():
    leads = [
        make_lead("Thorio"),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Thorio"]) == 1


def test_unknown_route_goes_to_review():
    leads = [
        make_lead("Unknown"),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Review"]) == 1
    assert len(queues["Unknown"]) if "Unknown" in queues else 0 == 0


def test_unqualified_lead_goes_to_review():
    leads = [
        make_lead(
            "Shiftr",
            qualified=False,
        ),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Shiftr"]) == 0
    assert len(queues["Review"]) == 1


def test_duplicate_lead_goes_to_review():
    leads = [
        make_lead(
            "Thorio",
            duplicate=True,
        ),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Thorio"]) == 0
    assert len(queues["Review"]) == 1


def test_zero_score_goes_to_review():
    leads = [
        make_lead(
            "Paxus",
            score=0,
        ),
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Paxus"]) == 0
    assert len(queues["Review"]) == 1


def test_get_route_queue_returns_only_requested_route():
    leads = [
        make_lead("Shiftr"),
        make_lead("Paxus"),
        make_lead("Thorio"),
    ]

    result = get_route_queue(
        leads,
        "Shiftr",
    )

    assert len(result) == 1
    assert result[0]["route"] == "Shiftr"


def test_queue_summary():
    leads = [
        make_lead("Shiftr"),
        make_lead("Paxus"),
        make_lead("Thorio"),
        make_lead("Review"),
        make_lead(
            "Shiftr",
            qualified=False,
        ),
    ]

    summary = summarize_queue(leads)

    assert summary["total"] == 5
    assert summary["shiftr"] == 1
    assert summary["paxus"] == 1
    assert summary["thorio"] == 1
    assert summary["review"] == 2
