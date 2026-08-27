from datetime import datetime, timezone
from typing import Any, Dict


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_delivery_attempt(
    lead: Dict[str, Any],
    partner: str,
) -> Dict[str, Any]:
    """
    Create a delivery attempt without mutating the lead.
    """

    return {
        "source_id": lead.get("source_id", ""),
        "company": lead.get("company", ""),
        "route": lead.get("route", ""),
        "partner": str(partner or "").strip(),
        "status": "pending",
        "attempted_at": _timestamp(),
    }


def complete_delivery_attempt(
    attempt: Dict[str, Any],
    success: bool,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Complete a delivery attempt and preserve its original data.
    """

    result = dict(attempt)

    result["status"] = (
        "delivered"
        if success
        else "failed"
    )

    result["reason"] = str(
        reason or ""
    ).strip()

    result["completed_at"] = _timestamp()

    return result


def delivery_attempt_succeeded(
    attempt: Dict[str, Any],
) -> bool:
    """
    Return True when the attempt completed successfully.
    """

    return (
        str(
            attempt.get("status", "")
        ).strip().lower()
        == "delivered"
    )


def delivery_attempt_failed(
    attempt: Dict[str, Any],
) -> bool:
    """
    Return True when the attempt failed.
    """

    return (
        str(
            attempt.get("status", "")
        ).strip().lower()
        == "failed"
    )
