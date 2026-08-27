from lead_engine.delivery_history import (
    delivery_event_count,
    has_delivery_event,
    last_delivery_event,
    record_delivery_event,
)


def test_record_delivery_event_creates_history():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
    }

    result = record_delivery_event(
        lead,
        "approved",
        "approved",
    )

    assert result is not lead
    assert len(result["delivery_history"]) == 1
    assert (
        result["delivery_history"][0]["event"]
        == "approved"
    )
    assert (
        result["delivery_history"][0]["status"]
        == "approved"
    )
    assert "timestamp" in result["delivery_history"][0]


def test_record_delivery_event_preserves_reason():
    lead = {
        "company": "Acme",
    }

    result = record_delivery_event(
        lead,
        "reviewed",
        "review",
        "route_evidence_mismatch",
    )

    event = result["delivery_history"][0]

    assert event["reason"] == "route_evidence_mismatch"


def test_multiple_events_are_preserved():
    lead = {}

    result = record_delivery_event(
        lead,
        "approved",
        "approved",
    )

    result = record_delivery_event(
        result,
        "delivered",
        "delivered",
    )

    assert delivery_event_count(result) == 2
    assert (
        result["delivery_history"][0]["event"]
        == "approved"
    )
    assert (
        result["delivery_history"][1]["event"]
        == "delivered"
    )


def test_last_delivery_event_returns_latest():
    lead = {}

    lead = record_delivery_event(
        lead,
        "approved",
        "approved",
    )

    lead = record_delivery_event(
        lead,
        "delivered",
        "delivered",
    )

    result = last_delivery_event(lead)

    assert result["event"] == "delivered"
    assert result["status"] == "delivered"


def test_last_delivery_event_without_history():
    assert last_delivery_event({}) == {}


def test_delivery_event_count_without_history():
    assert delivery_event_count({}) == 0


def test_has_delivery_event_finds_existing_event():
    lead = record_delivery_event(
        {},
        "approved",
        "approved",
    )

    assert has_delivery_event(
        lead,
        "approved",
    ) is True


def test_has_delivery_event_rejects_missing_event():
    lead = record_delivery_event(
        {},
        "approved",
        "approved",
    )

    assert has_delivery_event(
        lead,
        "delivered",
    ) is False


def test_original_lead_is_not_mutated():
    lead = {
        "company": "Acme",
    }

    result = record_delivery_event(
        lead,
        "approved",
        "approved",
    )

    assert "delivery_history" not in lead
    assert "delivery_history" in result
