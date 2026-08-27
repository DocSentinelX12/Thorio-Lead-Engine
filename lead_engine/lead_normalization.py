from __future__ import annotations

from typing import Any, Dict


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a normalized copy of a lead.

    String fields are trimmed while preserving all
    unrelated fields and the original lead.
    """

    result = dict(lead)

    string_fields = (
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

    for field in string_fields:
        if field in result:
            result[field] = _clean(result[field])

    return result
