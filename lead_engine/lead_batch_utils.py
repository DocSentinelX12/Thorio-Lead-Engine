from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_ranking import rank_leads


def batch_leads(
    leads: Iterable[Dict[str, Any]],
    batch_size: int,
) -> List[List[Dict[str, Any]]]:
    """
    Split leads into ordered batches.

    Each returned lead is copied so callers cannot accidentally
    mutate the original records.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    ranked = rank_leads(leads)

    return [
        ranked[index:index + batch_size]
        for index in range(0, len(ranked), batch_size)
    ]


def batch_count(
    leads: Iterable[Dict[str, Any]],
    batch_size: int,
) -> int:
    """Return the number of batches required for the leads."""

    return len(batch_leads(leads, batch_size))
