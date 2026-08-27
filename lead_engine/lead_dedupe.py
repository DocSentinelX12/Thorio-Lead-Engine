from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

from .lead_fingerprint import lead_fingerprint


def deduplicate_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Remove duplicate leads while preserving first-seen order.
    """

    seen: Set[str] = set()
    result: List[Dict[str, Any]] = []

    for lead in leads:
        fingerprint = lead_fingerprint(lead)

        if fingerprint in seen:
            continue

        seen.add(fingerprint)
        result.append(dict(lead))

    return result


def duplicate_count(
    leads: Iterable[Dict[str, Any]],
) -> int:
    """Return the number of duplicate records removed by deduplication."""

    records = list(leads)

    return len(records) - len(
        deduplicate_leads(records)
    )
