from .lead_queue_utils import (
    queue_counts,
    queue_ready_leads,
)


def make_lead(
    company="Acme",
    route="Shiftr",
    score=90,
    email="jane@example.com",
    delivery_status="approved",
):
    return {
        "company": company,
        "route": route,
        "lead_score": score,
        "contact_email": email,
        "delivery_status": delivery_status,
        "priority": "High",
    }


def test_queue_ready_lead():
    result = queue_ready_leads(
        [make_lead()]
    )

    assert len(result) == 1
    assert result[0]["company"] == "Acme"


def test_missing_company_is_excluded():
    result = queue_ready_leads(
        [make_lead(company="")]
    )

    assert result == []


def test_missing_route_is_excluded():
    result = queue_ready_leads(
        [make_lead(route="")]
    )

    assert result == []


def test_unapproved_lead_is_excluded():
    result = queue_ready_leads(
        [make_lead(delivery_status="pending")]
    )

    assert result == []


def test_missing_email_is_excluded():
    result = queue_ready_leads(
        [make_lead(email="")]
    )

    assert result == []


def test_queue_ready_leads_are_ranked():
    leads = [
        make_lead(
            company="Low",
            score=60,
            route="Shiftr",
        ),
        make_lead(
            company="High",
            score=95,
            route="Shiftr",
        ),
    ]

    result = queue_ready_leads(leads)

    assert result[0]["company"] == "High"
    assert result[1]["company"] == "Low"


def test_queue_ready_leads_returns_copies():
    lead = make_lead()

    result = queue_ready_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_queue_counts():
    leads = [
        make_lead(route="Shiftr"),
        make_lead(route="Shiftr"),
        make_lead(route="Paxus"),
        make_lead(route="Thorio"),
        make_lead(
            route="Review",
            delivery_status="pending",
        ),
    ]

    assert queue_counts(leads) == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 1,
    }


def test_queue_counts_empty():
    assert queue_counts([]) == {}


def test_queue_ready_accepts_generator():
    leads = (
        make_lead(company=f"Company {i}")
        for i in range(3)
    )

    result = queue_ready_leads(leads)

    assert len(result) == 3
