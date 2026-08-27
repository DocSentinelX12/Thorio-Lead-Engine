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
