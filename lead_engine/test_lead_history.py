from .lead_history import (
    history_for_lead,
    latest_history_event,
    record_history_event,
)


def test_record_history_event():
    lead = {
        "company": "Acme",
        "status": "qualified",
    }

    result = record_history_event(
        lead,
        "status_changed",
        previous_status="new",
        new_status="qualified",
        reason="Passed qualification",
    )

    assert result["company"] == "Acme"
    assert result["status"] == "qualified"
    assert len(result["history"]) == 1

    event = result["history"][0]

    assert event["event"] == "status_changed"
    assert event["previous_status"] == "new"
    assert event["new_status"] == "qualified"
    assert event["reason"] == "Passed qualification"
    assert event["timestamp"]


def test_history_preserves_existing_events():
    lead = {
        "company": "Acme",
        "history": [
            {
                "event": "discovered",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ],
    }

    result = record_history_event(
        lead,
        "qualified",
    )

    assert len(result["history"]) == 2
    assert result["history"][0]["event"] == "discovered"
    assert result["history"][1]["event"] == "qualified"


def test_history_for_lead_handles_missing_history():
    assert history_for_lead(
        {"company": "Acme"}
    ) == []


def test_latest_history_event():
    lead = record_history_event(
        {"company": "Acme"},
        "discovered",
    )

    lead = record_history_event(
        lead,
        "qualified",
    )

    latest = latest_history_event(lead)

    assert latest is not None
    assert latest["event"] == "qualified"


def test_latest_history_event_when_empty():
    assert latest_history_event(
        {"company": "Acme"}
    ) is None


def test_original_lead_is_not_mutated():
    lead = {
        "company": "Acme",
        "history": [],
    }

    result = record_history_event(
        lead,
        "discovered",
    )

    assert lead["history"] == []
    assert len(result["history"]) == 1
