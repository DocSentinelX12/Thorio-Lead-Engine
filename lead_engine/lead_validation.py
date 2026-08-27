from __future__ import annotations

from typing import Any, Dict, Iterable, List


REQUIRED_FIELDS = (
    "company",
    "route",
)


def validate_lead(lead: Dict[str, Any]) -> List[str]:
    """Return validation errors for a lead."""

    errors: List[str] = []

    for field in REQUIRED_FIELDS:
        value = lead.get(field)

        if value is None or str(value).strip() == "":
            errors.append(f"missing_{field}")

    if "lead_score" in lead:
        try:
            score = float(lead["lead_score"])

            if score < 0 or score > 100:
                errors.append("invalid_lead_score")

        except (TypeError, ValueError):
            errors.append("invalid_lead_score")

    return errors


def valid_lead(lead: Dict[str, Any]) -> bool:
    """Return True when the lead passes validation."""

    return not validate_lead(lead)


def invalid_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return copies of leads that fail validation."""

    return [
        dict(lead)
        for lead in leads
        if not valid_lead(lead)
    ]
