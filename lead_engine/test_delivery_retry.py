from lead_engine.delivery_retry import (
    delivery_attempt_number,
    delivery_retry_allowed,
    prepare_delivery_retry,
)


def test_retry_is_allowed_for_failed_attempt():
    attempt = {
        "status": "failed",
        "attempts": 1,
    }

    assert delivery_retry_allowed(attempt) is True


def test_retry_is_not_allowed_after_max_attempts():
    attempt = {
        "status": "failed",
        "attempts": 3,
    }

    assert delivery_retry_allowed(attempt) is False


def test_retry_is_not_allowed_for_delivered_attempt():
    attempt = {
        "status": "delivered",
        "attempts": 1,
    }

    assert delivery_retry_allowed(attempt) is False


def test_retry_respects_custom_max_attempts():
    attempt = {
        "status": "failed",
        "attempts": 2,
    }

    assert delivery_retry_allowed(
        attempt,
        max_attempts=2,
    ) is False

    assert delivery_retry_allowed(
        attempt,
        max_attempts=3,
    ) is True


def test_prepare_delivery_retry_increments_attempt():
    attempt = {
        "status": "failed",
        "attempts": 1,
    }

    result = prepare_delivery_retry(attempt)

    assert result["attempts"] == 2
    assert result["status"] == "pending"


def test_prepare_delivery_retry_does_not_mutate_original():
    attempt = {
        "status": "failed",
        "attempts": 1,
    }

    result = prepare_delivery_retry(attempt)

    assert attempt["attempts"] == 1
    assert attempt["status"] == "failed"
    assert result is not attempt


def test_attempt_number_normalizes_valid_value():
    assert delivery_attempt_number(
        {"attempts": 2}
    ) == 2


def test_attempt_number_handles_invalid_value():
    assert delivery_attempt_number(
        {"attempts": "invalid"}
    ) == 0


def test_attempt_number_handles_negative_value():
    assert delivery_attempt_number(
        {"attempts": -5}
    ) == 0


def test_new_attempt_can_retry():
    attempt = {
        "status": "pending",
        "attempts": 0,
    }

    assert delivery_retry_allowed(attempt) is True
