from __future__ import annotations

from typing import Any, Dict, Iterable, List


def chunk_leads(
    leads: Iterable[Dict[str, Any]],
    batch_size: int,
) -> List[List[Dict[str, Any]]]:
    """Split leads into ordered batches of at most batch_size records."""

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    records = [dict(lead) for lead in leads]

    return [
        records[index:index + batch_size]
        for index in range(0, len(records), batch_size)
    ]


def batch_count(
    leads: Iterable[Dict[str, Any]],
    batch_size: int,
) -> int:
    """Return the number of batches required."""

    return len(
        chunk_leads(leads, batch_size)
    )
