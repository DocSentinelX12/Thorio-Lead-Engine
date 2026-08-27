from .lead_queue import (
    build_lead_queue,
    queue_counts,
)


def make_lead(
    *,
    company,
    route,
    score,
    status="qualified",
):
    return {
        "company": company,
        "route": route,
        "lead_score": score,
        "status": status,
    }


def test_approved_leads_enter_partner_queue():
    leads = [
        make_lead(
            company="Shiftr Co",
            route="Shiftr",
            score=90,
        ),
        make_lead(
            company="Paxus Co",
            route="Paxus",
            score=80,
        ),
        make_lead(
            company="Thorio Co",
            route="Thorio",
            score=70,
        ),
    ]

    result = build_lead_queue(leads)

    assert len(result["Shiftr"]) == 1
    assert len(result["Paxus"]) == 1
    assert len(result["Thorio"]) == 1
    assert result["Review"] == []


def test_low_score_lead_goes_to_review():
    lead = make_lead(
        company="Review Co",
        route="Thorio",
        score=25,
    )

    result = build_lead_queue([lead])

    assert result["Thorio"] == []
    assert len(result["Review"]) == 1
    assert result["Review"][0]["company"] == "Review Co"


def test_rejected_lead_is_excluded():
    lead = make_lead(
        company="Rejected Co",
        route="Thorio",
        score=0,
    )

    result = build_lead_queue([lead])

    assert result["Thorio"] == []
    assert result["Review"] == []


def test_unknown_route_goes_to_review():
    lead = make_lead(
        company="Unknown Co",
        route="Unknown",
        score=90,
    )

    result = build_lead_queue([lead])

    assert result["Shiftr"] == []
    assert result["Paxus"] == []
    assert result["Thorio"] == []
    assert len(result["Review"]) == 1


def test_queue_counts():
    leads = [
        make_lead(
            company="A",
            route="Shiftr",
            score=90,
        ),
        make_lead(
            company="B",
            route="Shiftr",
            score=80,
        ),
        make_lead(
            company="C",
            route="Paxus",
            score=70,
        ),
        make_lead(
            company="D",
            route="Thorio",
            score=20,
        ),
        make_lead(
            company="E",
            route="Thorio",
            score=0,
        ),
    ]

    assert queue_counts(leads) == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 0,
        "Review": 1,
    }


def test_queue_copies_lead_records():
    lead = make_lead(
        company="Acme",
        route="Thorio",
        score=90,
    )

    result = build_lead_queue([lead])

    assert result["Thorio"][0] == lead
    assert result["Thorio"][0] is not lead
