from __future__ import annotations

from typing import Any, Dict


VALID_STATUSES = (
    "new",
    "qualified",
    "approved",
    "delivered",
    "rejected",
)


ALLOWED_TRANSITIONS = {
    "new": {
        "new",
        "qualified",
        "rejected",
    },
    "qualified": {
        "qualified",
        "approved",
        "rejected",
    },
    "approved": {
        "approved",
        "delivered",
        "rejected",
    },
    "delivered": {
        "delivered",
    },
    "rejected": {
        "rejected",
        "new",
    },
}


def normalize_status(value: Any) -> str:
    """
    Normalize a lead status value.
    """

    return str(value or "").strip().lower()


def is_valid_status(value: Any) -> bool:
    """
    Return True when the supplied status is supported.
    """

    return normalize_status(value) in VALID_STATUSES


def can_transition(
    current_status: Any,
    new_status: Any,
) -> bool:
    """
    Return True when a lead may move from its current status
    to the requested new status.
    """

    current = normalize_status(current_status)
    new = normalize_status(new_status)

    if current not in VALID_STATUSES:
        return False

    if new not in VALID_STATUSES:
        return False

    return new in ALLOWED_TRANSITIONS[current]


def transition_lead(
    lead: Dict[str, Any],
    new_status: str,
) -> Dict[str, Any]:
    """
    Return a copy of a lead with its status transitioned.

    Invalid transitions raise ValueError instead of silently
    corrupting the lead lifecycle.
    """

    result = dict(lead)

    current_status = normalize_status
