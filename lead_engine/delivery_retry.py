from typing import Any, Dict


DEFAULT_MAX_ATTEMPTS = 3


def delivery_retry_allowed(
    attempt: Dict[str, Any],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> bool:
    """
    Determine whether another delivery attempt is allowed.
    """

    if max_attempts < 1:
        return False

    status = str(
        attempt.get("status", "")
    ).strip().lower()

    if status == "delivered":
        return False

    attempts = attempt.get("attempts", 0)

    try:
        attempts = int(attempts)
    except (TypeError, ValueError):
        attempts = 0

    return attempts < max_attempts


def prepare_delivery_retry(
    attempt: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Prepare a failed or pending attempt for another try.

    The original attempt is never mutated.
    """

    result = dict(attempt)

    attempts = result.get("attempts", 0)

    try:
        attempts = int(attempts)
    except (TypeError, ValueError):
        attempts = 0

    result["attempts"] = attempts + 1
    result["status"] = "pending"

    return result


def delivery_attempt_number(
    attempt: Dict[str, Any],
) -> int:
    """
    Return the normalized attempt number.
    """

    value = attempt.get("attempts", 0)

    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
