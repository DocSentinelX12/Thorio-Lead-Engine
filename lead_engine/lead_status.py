from __future__ import annotations

from typing import Any, Dict


VALID_STATUSES = (
    "new",
    "qualified",
    "contacted",
    "replied",
    "interested",
    "referred",
    "converted",
    "rejected",
)


def normalize_status(status: Any) -> str:
    """
    Normalize a lead status into a supported status value.

    Unknown, empty, or invalid values safely become "new".
    """
    if status is None:
        return "new"

    normalized = str(status).strip().lower()

    aliases = {
        "": "new",
        "unqualified": "rejected",
        "discarded": "rejected",
        "closed": "rejected",
        "pending": "new",
        "open": "new",
        "qualified_lead": "qualified",
        "contacted_lead": "contacted",
        "responded": "replied",
        "converted_lead": "converted",
    }

    normalized = aliases.get(normalized, normalized)

    if normalized not in VALID_STATUSES:
        return "new"

    return normalized


def is_valid_status(status: Any) -> bool:
    """Return True when status is one of the supported lead statuses."""
    if status is None:
        return False

    return str(status).strip().lower() in VALID_STATUSES


def status_metadata(status: Any) -> Dict[str, Any]:
    """
    Return normalized status information used by the lead engine.
    """
    normalized = normalize_status(status)

    terminal = normalized in {"converted", "rejected"}

    return {
        "status": normalized,
        "terminal": terminal,
        "active": not terminal,
    }
