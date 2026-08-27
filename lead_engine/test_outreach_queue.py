from lead_engine.outreach_queue import (
    ROUTES,
    build_outreach_queue,
    get_route_leads,
    summarize_queue,
)


def test_build_outreach_queue_separates_routes():
    leads = [
        {
            "company": "Shiftr Corp",
            "route": "Shiftr",
        },
        {
            "company": "Paxus Corp",
            "route": "Paxus",
        },
        {
            "company": "Thorio Corp",
            "route": "Thorio",
        },
        {
            "company": "Needs Review",
            "route": "Review",
        },
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Shiftr"]) == 1
    assert len(queues["Paxus"]) == 1
    assert len(queues["Thorio"]) == 1
    assert len(queues["Review"]) == 1


def test_unknown_route_goes_to_review():
    leads = [
        {
            "company": "Unknown Corp",
            "route": "SomethingElse",
        }
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Review"]) == 1
    assert queues["Review"][0]["company"] == "Unknown Corp"


def test_missing_route_goes_to_review():
    leads = [
        {
            "company": "Missing Route Corp",
        }
    ]

    queues = build_outreach_queue(leads)

    assert len(queues["Review"]) == 1


def test_summarize_queue_returns_all_routes():
    leads = [
        {"route": "Shiftr"},
        {"route": "Shiftr"},
        {"route": "Paxus"},
        {"route": "Thorio"},
        {"route": "Review"},
    ]

    summary = summarize_queue(leads)

    assert set(summary) == set(ROUTES)
    assert summary["Shiftr"] == 2
    assert summary["Paxus"] == 1
    assert summary["Thorio"] == 1
    assert summary["Review"] == 1


def test_get_route_leads_returns_only_requested_route():
    leads = [
        {
            "company": "Shiftr Corp",
            "route": "Shiftr",
        },
        {
            "company": "Paxus Corp",
            "route": "Paxus",
        },
    ]

    result = get_route_leads(
        leads,
        "Shiftr",
    )

    assert len(result) == 1
    assert result[0]["company"] == "Shiftr Corp"


def test_get_route_leads_unknown_route_returns_empty():
    leads = [
        {
            "company": "Example Corp",
            "route": "Thorio",
        }
    ]

    assert get_route_leads(
        leads,
        "NotARoute",
    ) == []
