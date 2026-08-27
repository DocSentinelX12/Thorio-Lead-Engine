from typing import Dict


DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY = 30
DEFAULT_MAX_DELAY = 3600


def retry_delay(
    attempts: int,
    base_delay: int = DEFAULT_BASE_DELAY,
    max_delay: int = DEFAULT_MAX_DELAY,
) -> int:
    """
    Calculate exponential retry delay.

    The first retry waits base_delay seconds.
    Each subsequent retry doubles the delay.
    The delay is capped at max_delay.
    """

    if attempts <= 0:
        return 0

    delay = base_delay * (2 ** (attempts - 1))

    return min(delay, max_delay)


def should_retry(
    attempts: int,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> bool:
    """
    Return whether another synchronization attempt is allowed.
    """

    return attempts < max_attempts


def retry_state(
    attempts: int,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Dict[str, object]:
    """
    Return retry information for a queued lead.
    """

    return {
        "attempts": attempts,
        "max_attempts": max_attempts,
        "retryable": should_retry(
            attempts,
            max_attempts,
        ),
        "delay_seconds": retry_delay(
            attempts
        ),
    }
