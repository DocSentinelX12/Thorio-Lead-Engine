from __future__ import annotations

from typing import Any, Dict, Iterable, List


PRIORITY_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def sort_by_score(
    leads: Iterable[Dict[str, Any]],
    descending: bool = True,
) -> List[Dict[str, Any]]:
    """Sort leads by numeric lead score."""

    records = [dict(lead) for lead in leads]

    def score(lead: Dict[str, Any]) -> float:
        try:
            return float(lead.get("lead_score", 0))
        except (TypeError, ValueError):
            return 0.0

    return sorted(
        records,
        key=score,
        reverse=descending,
    )


def sort_by_priority(
    leads: Iterable[Dict[str, Any]],
    descending: bool = True,
) -> List[Dict[str, Any]]:
    """Sort leads by priority."""

    records = [dict(lead) for lead in leads]

    def priority(lead: Dict[str, Any]) -> int:
        return PRIORITY_ORDER.get(
            str(lead.get("priority", "")).strip().lower(),
            0,
        )

    return sorted(
        records,
        key=priority,
        reverse=descending,
    )
