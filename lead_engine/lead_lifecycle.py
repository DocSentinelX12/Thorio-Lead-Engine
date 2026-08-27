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
    """Normalize a lead status value."""
    return str(value or "").strip().lower()


def is_valid_status(value: Any) -> bool:
    """Return True when the supplied status is supported."""
    return normalize_status(value) in VALID_STATUSES


def can_transition(
    current_status: Any,
    new_status: Any,
) -> bool:
    """Return whether a lead may move to the requested status."""

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
    Return a copy of the lead with the requested status.

    Invalid lifecycle transitions raise ValueError.
    """

    result = dict(lead)

    current_status = normalize_status(
        result.get("status", "new")
    )

    target_status = normalize_status(
        new_status
    )

    if not can_transition(
        current_status,
        target_status,
    ):
        raise ValueError(
            "Invalid lead status transition: "
            f"{current_status!r} -> {target_status!r}"
        )

    result["status"] = target_status

    return result
