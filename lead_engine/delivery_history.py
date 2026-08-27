from datetime import datetime, timezone
from typing import Any, Dict, List


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_delivery_event(
    lead: Dict[str, Any],
    event: str,
    status: str,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Add a delivery event to a lead's delivery history.

    The original lead is never mutated.
    """

    result = dict(lead)

    history = list(
        result.get("delivery_history", [])
    )

    history.append(
        {
            "event": str(event).strip(),
            "status": str(status).strip(),
            "reason": str(reason or "").strip(),
            "timestamp": _timestamp(),
        }
    )

    result["delivery_history"] = history

    return result


def last_delivery_event(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return the most recent delivery event.

    Returns an empty dictionary when no history exists.
    """

    history = lead.get(
        "delivery_history",
        [],
    )

    if not history:
        return {}

    return dict(history[-1])


def delivery_event_count(
    lead: Dict[str, Any],
) -> int:
    """
    Return the number of recorded delivery events.
    """

    return len(
        lead.get(
            "delivery_history",
            [],
        )
    )


def has_delivery_event(
    lead: Dict[str, Any],
    event: str,
) -> bool:
    """
    Return True when the specified delivery event
    exists in the lead history.
    """

    expected = str(event).strip()

    return any(
        str(item.get("event", "")).strip()
        == expected
        for item in lead.get(
            "delivery_history",
            [],
        )
    )
