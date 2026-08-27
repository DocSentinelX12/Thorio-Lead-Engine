from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_normalize import normalize_lead
from .lead_priority import assign_priority
from .lead_validation import validate_lead


def prepare_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize and assign priority to a lead.

    The returned record is a new dictionary.
    """

    normalized = normalize_lead(lead)
    return assign_priority(normalized)


def valid_prepared_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prepare leads and return only records that pass validation."""

    result: List[Dict[str, Any]] = []

    for lead in leads:
        prepared = prepare_lead(lead)

        if not validate_lead(prepared):
            result.append(prepared)

    return result
