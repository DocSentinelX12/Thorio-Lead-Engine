from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_normalize import normalize_lead


EXPORT_FIELDS = (
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
    "potential_routes",
    "lead_score",
    "priority",
    "status",
    "delivery_status",
    "delivery_reason",
)


def prepare_export_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a normalized copy containing the standard export fields."""

    normalized = normalize_lead(lead)

    return {
        field: normalized[field]
        for field in EXPORT_FIELDS
        if field in normalized
    }


def prepare_export(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prepare multiple leads for export without mutating the originals."""

    return [
        prepare_export_lead(lead)
        for lead in leads
    ]
