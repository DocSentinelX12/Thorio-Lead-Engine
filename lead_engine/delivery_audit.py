from typing import Any, Dict, List


def audit_delivery_attempt(
    lead: Dict[str, Any],
    attempt: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create an immutable-style audit entry describing a delivery attempt.
    """

    return {
        "source_id": lead.get("source_id", ""),
        "company": lead.get("company", ""),
        "route": lead.get("route", ""),
        "partner": attempt.get("partner", ""),
        "status": attempt.get("status", ""),
        "reason": attempt.get("reason", ""),
        "attempts": attempt.get("attempts", 0),
        "attempted_at": attempt.get("attempted_at", ""),
        "completed_at": attempt.get("completed_at", ""),
    }


def append_delivery_audit(
    lead: Dict[str, Any],
    attempt: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a copy of the lead with the delivery attempt added
    to its audit history.
    """

    result = dict(lead)

    history: List[Dict[str, Any]] = [
        dict(item)
        for item in result.get(
            "delivery_audit",
            [],
        )
    ]

    history.append(
        audit_delivery_attempt(
            result,
            attempt,
        )
    )

    result["delivery_audit"] = history

    return result


def delivery_audit_count(
    lead: Dict[str, Any],
) -> int:
    """
    Return the number of delivery audit entries.
    """

    return len(
        lead.get(
            "delivery_audit",
            [],
        )
    )


def last_delivery_audit(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return the most recent delivery audit entry.
    """

    history = lead.get(
        "delivery_audit",
        [],
    )

    if not history:
        return {}

    return dict(history[-1])
