from lead_engine.delivery_audit import (
    append_delivery_audit,
    audit_delivery_attempt,
    delivery_audit_count,
    last_delivery_audit,
)


def test_audit_delivery_attempt_contains_lead_and_attempt_data():
    lead = {
        "source_id": "lead-001",
        "company": "Acme",
        "route": "Shiftr",
    }

    attempt = {
        "partner": "Shiftr",
        "status": "delivered",
        "reason": "",
        "attempts": 1,
        "attempted_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:01:00+00:00",
    }

    result = audit_delivery_attempt(
        lead,
        attempt,
    )

    assert result["source_id"] == "lead-001"
    assert result["company"] == "Acme"
    assert result["route"] == "Shiftr"
    assert result["partner"] == "Shiftr"
    assert result["status"] == "delivered"
    assert result["attempts"] == 1


def test_append_delivery_audit_adds_entry():
    lead = {
        "source_id": "lead-002",
        "company": "Acme",
        "route": "Paxus",
    }

    attempt = {
        "partner": "Paxus",
        "status": "failed",
        "reason": "temporary_failure",
        "attempts": 1,
    }

    result = append_delivery_audit(
        lead,
        attempt,
    )

    assert delivery_audit_count(result) == 1
    assert (
        result["delivery_audit"][0]["partner"]
        == "Paxus"
    )
    assert (
        result["delivery_audit"][0]["status"]
        == "failed"
    )


def test_append_delivery_audit_does_not_mutate_original():
    lead = {
        "company": "Acme",
    }

    attempt = {
        "partner": "Thorio",
        "status": "delivered",
    }

    result = append_delivery_audit(
        lead,
        attempt,
    )

    assert "delivery_audit" not in lead
    assert "delivery_audit" in result
    assert result is not lead


def test_multiple_audits_are_preserved():
    lead = {}

    lead = append_delivery_audit(
        lead,
        {
            "partner": "Shiftr",
            "status": "failed",
        },
    )

    lead = append_delivery_audit(
        lead,
        {
            "partner": "Shiftr",
            "status": "delivered",
        },
    )

    assert delivery_audit_count(lead) == 2


def test_last_delivery_audit_returns_latest():
    lead = {}

    lead = append_delivery_audit(
        lead,
        {
            "partner": "Shiftr",
            "status": "failed",
        },
    )

    lead = append_delivery_audit(
        lead,
        {
            "partner": "Shiftr",
            "status": "delivered",
        },
    )

    result = last_delivery_audit(lead)

    assert result["status"] == "delivered"


def test_last_delivery_audit_without_history():
    assert last_delivery_audit({}) == {}


def test_delivery_audit_count_without_history():
    assert delivery_audit_count({}) == 0
