from __future__ import annotations

from typing import Any, Dict, Iterable, List


def batch_leads(
    leads: Iterable[Dict[str, Any]],
    batch_size: int,
) -> List[List[Dict[str, Any]]]:
    """
    Split leads into ordered batches.

    The input records are copied so callers can safely modify
    returned batches without changing the original records.
    """

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
    """Return the number of batches required for the leads."""

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    count = len(list(leads))

    if count == 0:
        return 0

    return (count + batch_size - 1) // batch_size
