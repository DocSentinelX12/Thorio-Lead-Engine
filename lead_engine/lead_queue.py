from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_dedupe import deduplicate_leads
from .lead_pipeline_utils import prepare_lead


def build_lead_queue(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build the working lead queue.

    Leads are deduplicated first, then normalized and assigned priority.
    """

    unique_leads = deduplicate_leads(leads)

    return [
        prepare_lead(lead)
        for lead in unique_leads
    ]


def queue_size(
    leads: Iterable[Dict[str, Any]],
) -> int:
    """Return the number of unique leads in the queue."""

    return len(
        build_lead_queue(leads)
    )
