from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_filter import filter_by_min_score
from .lead_pipeline_utils import prepare_lead
from .lead_sort import sort_by_score


def process_leads(
    leads: Iterable[Dict[str, Any]],
    minimum_score: float = 0,
) -> List[Dict[str, Any]]:
    """Prepare, optionally filter, and sort leads for downstream processing."""

    prepared = [
        prepare_lead(lead)
        for lead in leads
    ]

    filtered = filter_by_min_score(
        prepared,
        minimum_score,
    )

    return sort_by_score(filtered)


def top_leads(
    leads: Iterable[Dict[str, Any]],
    limit: int = 10,
    minimum_score: float = 0,
) -> List[Dict[str, Any]]:
    """Return the highest-scoring leads up to the requested limit."""

    if limit < 0:
        raise ValueError("limit must not be negative")

    return process_leads(
        leads,
        minimum_score,
    )[:limit]
