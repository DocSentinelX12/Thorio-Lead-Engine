from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_history_event(
    lead: Dict[str, Any],
    event: str,
    *,
    previous_status: str = "",
    new_status: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    """
    Return a copy of a lead with a new lifecycle history event.

    Existing history is preserved and every event receives a UTC
    timestamp.
    """

    result = dict(lead)

    existing_history = result.get(
        "history",
        [],
    )

    if not isinstance(existing_history, list):
        existing_history = []

    history = [
        dict(item)
        for item in existing_history
        if isinstance(item, dict)
    ]

    history.append(
        {
            "event": str(event or "").strip(),
            "previous_status": str(
                previous_status or ""
            ).strip(),
            "new_status": str(
                new_status or ""
            ).strip(),
            "reason": str(
                reason or ""
            ).strip(),
            "timestamp": _timestamp(),
        }
    )

    result["history"] = history

    return result


def history_for_lead(
    lead: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Return normalized lifecycle history for a lead.
    """

    history = lead.get(
        "history",
        [],
    )

    if not isinstance(history, list):
        return []

    return [
        dict(item)
        for item in history
        if isinstance(item, dict)
    ]


def latest_history_event(
    lead: Dict[str, Any],
) -> Dict[str, Any] | None:
    """
    Return the most recent lifecycle event, if one exists.
    """

    history = history_for_lead(lead)

    if not history:
        return None

    return history[-1]
