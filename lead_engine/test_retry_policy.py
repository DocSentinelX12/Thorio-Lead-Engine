from .retry_policy import (
    retry_delay,
    retry_state,
    should_retry,
)


def test_first_retry_uses_base_delay():
    assert retry_delay(1) == 30


def test_retry_delay_doubles():
    assert retry_delay(2) == 60
    assert retry_delay(3) == 120
    assert retry_delay(4) == 240


def test_retry_delay_is_capped():
    assert retry_delay(20) == 3600


def test_zero_attempts_have_no_delay():
    assert retry_delay(0) == 0


def test_retry_allowed_before_limit():
    assert should_retry(0) is True
    assert should_retry(4) is True


def test_retry_stops_at_limit():
    assert should_retry(5) is False
    assert should_retry(6) is False


def test_retry_state_contains_operational_metadata():
    result = retry_state(3)

    assert result["attempts"] == 3
    assert result["max_attempts"] == 5
    assert result["retryable"] is True
    assert result["delay_seconds"] == 120


def test_lead_error_retries_are_durably_bounded_and_quarantined(tmp_path):
    from .database import LeadDB

    db = LeadDB(data_dir=str(tmp_path))
    db.insert_if_new({"fingerprint": "retry-bound-001", "company": "Retry Corp"})

    for attempt in range(5):
        result = db.mark_error("retry-bound-001", f"failure-{attempt + 1}")

    assert result["attempts"] == 5
    assert result["retryable"] is False
    assert result["quarantined"] is True
    assert db.pending(limit=50) == []

    state = db.get_sync_state("retry-bound-001")
    assert state["synced"] is False
    assert state["attempts"] == 5
    assert state["last_error"] == "failure-5"


def test_quarantined_lead_requires_deliberate_requeue_and_gets_a_fresh_bounded_cycle(tmp_path):
    from .database import LeadDB
    from .retry_policy import DEFAULT_MAX_ATTEMPTS
    db = LeadDB(data_dir=str(tmp_path))
    lead = {"fingerprint": "quarantine-requeue-001", "company": "Recovery Corp"}
    assert db.insert_if_new(lead)
    for index in range(DEFAULT_MAX_ATTEMPTS):
        result = db.mark_error(lead["fingerprint"], f"failure-{index + 1}")
    assert result["quarantined"] is True
    assert db.pending(limit=50) == []
    with __import__("pytest").raises(ValueError, match="not quarantined"):
        db.requeue_quarantined(lead["fingerprint"], "should not be early")
    state = db.requeue_quarantined(lead["fingerprint"], "operator verified Airtable availability")
    assert state["synced"] is False
    assert state["attempts"] == 0
    assert "Quarantine requeued:" in state["last_error"]
    assert len(db.pending(limit=50)) == 1
