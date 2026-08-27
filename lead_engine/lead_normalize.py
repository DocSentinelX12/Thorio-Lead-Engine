from __future__ import annotations

from typing import Any, Dict


TEXT_FIELDS = (
    "source",
    "source_id",
    "url",
    "company",
    "person",
    "contact_name",
    "contact_title",
    "contact_email",
    "signal",
    "evidence",
    "route",
    "status",
    "delivery_status",
    "delivery_reason",
    "priority",
)


def normalize_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize common lead text fields without changing the
    original record.
    """

    normalized = dict(lead)

    for field in TEXT_FIELDS:
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = value.strip()

    if "contact_email" in normalized:
        email = normalized.get("contact_email")

        if isinstance(email, str):
            normalized["contact_email"] = email.lower()

    return normalized
