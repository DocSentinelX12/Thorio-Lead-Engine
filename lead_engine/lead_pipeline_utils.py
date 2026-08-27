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
    """
    Prepare leads and return records that are valid for the
    preparation stage of the pipeline.

    Routing is intentionally not required at this stage because
    routing may be assigned later in the pipeline.
    """

    result: List[Dict[str, Any]] = []

    for lead in leads:
        prepared = prepare_lead(lead)
        errors = validate_lead(prepared)

        preparation_errors = [
            error
            for error in errors
            if error != "missing_route"
        ]

        if not preparation_errors:
            result.append(prepared)

    return result
