from lead_engine.delivery_policy import MIN_DELIVERY_SCORE
from lead_engine.outreach_queue import (
    ROUTES,
    build_outreach_queue,
    get_route_leads,
    summarize_queue,
)


def make_lead(
    route,
    signal,
    evidence=None,
):
    return {
        "company": "Acme",
        "route": route,
        "lead_score": MIN_DELIVERY_SCORE,
        "signal": signal,
        "evidence": (
            evidence
            or f"Acme has a {signal} opening."
        ),
        "url": "https://example.com/jobs/123",
    }


def test_build_outreach_queue_separates_approved_routes():
    leads = [
        make_lead(
            "Shiftr",
            "remote software engineer",
        ),
        make_lead(
            "Paxus",
            "contract staffing need",
            "Acme needs contractors for a technology project.",
        ),
        make_lead(
            "Thorio",
            "remote product designer",
        ),
        {
            "company": "Needs Review",
            "route": "Review",
        },
    ]

    queues = build_outreach_queue(
        leads
    )

    assert len(queues["Shiftr"]) == 1
    assert len(queues["Paxus"]) == 1
    assert len(queues["Thorio"]) == 1
    assert len(queues["Review"]) == 1


def test_unknown_route_goes_to_review():
    leads = [
        {
            "company": "Unknown Corp",
            "route": "SomethingElse",
            "lead_score": 100,
            "signal": "software engineer",
            "evidence": "Company needs a software engineer.",
            "url": "https://example.com/jobs/unknown",
        }
    ]

    queues = build_outreach_queue(
        leads
    )

    assert len(queues["Shiftr"]) == 0
    assert len(queues["Paxus"]) == 0
    assert len(queues["Thorio"]) == 0
    assert len(queues["Review"]) == 1
    assert (
        queues["Review"][0]["delivery_reason"]
        == "unsupported_route"
    )


def test_missing_route_goes_to_review():
    leads = [
        {
            "company": "Missing Route Corp",
            "lead_score": 100,
            "signal": "software engineer",
            "evidence": "Company needs a software engineer.",
            "url": "https://example.com/jobs/missing-route",
        }
    ]

    queues = build_outreach_queue(
        leads
    )

    assert len(queues["Review"]) == 1
    assert (
        queues["Review"][0]["delivery_reason"]
        == "unsupported_route"
    )


def test_route_mismatch_never_enters_outreach_queue():
    leads = [
        make_lead(
            "Shiftr",
            "office manager",
            "Company is hiring an office manager.",
        )
    ]

    queues = build_outreach_queue(
        leads
    )

    assert queues["Shiftr"] == []
    assert len(queues["Review"]) == 1
    assert (
        queues["Review"][0]["delivery_reason"]
        == "route_evidence_mismatch"
    )


def test_low_score_lead_stays_in_review():
    lead = make_lead(
        "Shiftr",
        "software engineer",
    )

    lead["lead_score"] = (
        MIN_DELIVERY_SCORE - 1
    )

    queues = build_outreach_queue(
        [lead]
    )

    assert queues["Shiftr"] == []
    assert len(queues["Review"]) == 1
    assert (
        queues["Review"][0]["delivery_reason"]
        == "delivery_policy_rejected"
    )


def test_summarize_queue_returns_all_routes():
    leads = [
        make_lead(
            "Shiftr",
            "remote software engineer",
        ),
        make_lead(
            "Shiftr",
            "remote software engineer",
        ),
        make_lead(
            "Paxus",
            "contract staffing need",
            "Acme needs contractors for a technology project.",
        ),
        make_lead(
            "Thorio",
            "remote product designer",
        ),
        {
            "company": "Review Corp",
            "route": "Review",
        },
    ]

    summary = summarize_queue(
        leads
    )

    assert set(summary) == set(ROUTES)
    assert summary["Shiftr"] == 2
    assert summary["Paxus"] == 1
    assert summary["Thorio"] == 1
    assert summary["Review"] == 1


def test_get_route_leads_returns_only_approved_requested_route():
    leads = [
        make_lead(
            "Shiftr",
            "remote software engineer",
        ),
        make_lead(
            "Paxus",
            "contract staffing need",
            "Acme needs contractors for a technology project.",
        ),
        make_lead(
            "Thorio",
            "remote product designer",
        ),
    ]

    result = get_route_leads(
        leads,
        "Shiftr",
    )

    assert len(result) == 1
    assert result[0]["company"] == "Acme"
    assert result[0]["route"] == "Shiftr"


def test_get_route_leads_does_not_return_rejected_lead():
    leads = [
        make_lead(
            "Shiftr",
            "office manager",
            "Company is hiring an office manager.",
        )
    ]

    assert get_route_leads(
        leads,
        "Shiftr",
    ) == []


def test_get_route_leads_unknown_route_returns_empty():
    leads = [
        make_lead(
            "Thorio",
            "remote product designer",
        )
    ]

    assert get_route_leads(
        leads,
        "NotARoute",
    ) == []
