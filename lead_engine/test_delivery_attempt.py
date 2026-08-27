from lead_engine.delivery_attempt import (
    complete_delivery_attempt,
    create_delivery_attempt,
    delivery_attempt_failed,
    delivery_attempt_succeeded,
)


def test_create_delivery_attempt():
    lead = {
        "source_id": "lead-001",
        "company": "Acme",
        "route": "Shiftr",
    }

    attempt = create_delivery_attempt(
        lead,
        "Shiftr",
    )

    assert attempt["source_id"] == "lead-001"
    assert attempt["company"] == "Acme"
    assert attempt["route"] == "Shiftr"
    assert attempt["partner"] == "Shiftr"
    assert attempt["status"] == "pending"
    assert "attempted_at" in attempt


def test_create_delivery_attempt_does_not_mutate_lead():
    lead = {
        "source_id": "lead-002",
        "company": "Acme",
        "route": "Paxus",
    }

    create_delivery_attempt(
        lead,
        "Paxus",
    )

    assert lead == {
        "source_id": "lead-002",
        "company": "Acme",
        "route": "Paxus",
    }


def test_complete_successful_delivery_attempt():
    attempt = {
        "partner": "Thorio",
        "status": "pending",
    }

    result = complete_delivery_attempt(
        attempt,
        True,
    )

    assert result["status"] == "delivered"
    assert result["reason"] == ""
    assert "completed_at" in result


def test_complete_failed_delivery_attempt():
    attempt = {
        "partner": "Shiftr",
        "status": "pending",
    }

    result = complete_delivery_attempt(
        attempt,
        False,
        "partner_unavailable",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "partner_unavailable"
    assert "completed_at" in result


def test_delivery_attempt_succeeded():
    attempt = {
        "status": "delivered",
    }

    assert delivery_attempt_succeeded(attempt) is True
    assert delivery_attempt_failed(attempt) is False


def test_delivery_attempt_failed():
    attempt = {
        "status": "failed",
    }

    assert delivery_attempt_failed(attempt) is True
    assert delivery_attempt_succeeded(attempt) is False


def test_pending_attempt_is_neither_success_nor_failure():
    attempt = {
        "status": "pending",
    }

    assert delivery_attempt_succeeded(attempt) is False
    assert delivery_attempt_failed(attempt) is False


def test_complete_attempt_does_not_mutate_original():
    attempt = {
        "partner": "Shiftr",
        "status": "pending",
    }

    result = complete_delivery_attempt(
        attempt,
        True,
    )

    assert attempt["status"] == "pending"
    assert result["status"] == "delivered"
