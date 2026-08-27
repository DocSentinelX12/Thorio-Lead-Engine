from __future__ import annotations

from typing import Any, Dict, List


REQUIRED_FIELDS = (
    "source",
    "source_id",
    "url",
    "company",
    "signal",
    "evidence",
)


def validate_lead(
    lead: Dict[str, Any],
) -> List[str]:
    """
    Validate the minimum fields required for a lead.

    Returns a list of validation errors. An empty list means
    the lead satisfies the required-field checks.
    """

    errors: List[str] = []

    for field in REQUIRED_FIELDS:
        value = lead.get(field)

        if value is None:
            errors.append(f"missing_{field}")
            continue

        if isinstance(value, str) and not value.strip():
            errors.append(f"missing_{field}")

    return errors


def is_valid_lead(
    lead: Dict[str, Any],
) -> bool:
    """Return True when the lead passes required-field validation."""

    return not validate_lead(lead)
