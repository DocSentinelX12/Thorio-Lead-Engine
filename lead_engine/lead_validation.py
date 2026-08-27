from __future__ import annotations

from typing import Any, Dict, List


REQUIRED_LEAD_FIELDS = (
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
    Return a list of validation errors.

    An empty list means the lead contains all required
    information needed by the engine.
    """

    errors: List[str] = []

    for field in REQUIRED_LEAD_FIELDS:
        value = lead.get(field)

        if value is None:
            errors.append(
                f"missing_{field}"
            )
            continue

        if not str(value).strip():
            errors.append(
                f"missing_{field}"
            )

    url = str(
        lead.get("url", "")
        or ""
    ).strip()

    if url and not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        errors.append("invalid_url")

    return errors


def is_valid_lead(
    lead: Dict[str, Any],
) -> bool:
    """Return True when the lead passes validation."""

    return not validate_lead(lead)


def validation_result(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a structured validation result without
    mutating the original lead.
    """

    errors = validate_lead(lead)

    return {
        "valid": not errors,
        "errors": errors,
    }
