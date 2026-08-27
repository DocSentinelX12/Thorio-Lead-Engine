from __future__ import annotations

from typing import Any, Dict, Iterable, List


_PRIORITY_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def sort_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Sort leads by priority and score, highest first.

    Original records are not mutated.
    """

    records = [dict(lead) for lead in leads]

    def sort_key(lead: Dict[str, Any]):
        priority = str(
            lead.get("priority", "")
            or ""
        ).strip().lower()

        try:
            score = float(
                lead.get("lead_score", 0)
            )
        except (TypeError, ValueError):
            score = 0

        return (
            _PRIORITY_ORDER.get(priority, 0),
            score,
        )

    return sorted(
        records,
        key=sort_key,
        reverse=True,
    )
