from __future__ import annotations

from typing import Any, Dict, Iterable, List


PRIORITY_ORDER = {
    "Critical": 4,
    "High": 3,
    "Medium": 2,
    "Low": 1,
}


def ranking_score(lead: Dict[str, Any]) -> float:
    """Return the numeric score used to rank a lead."""

    try:
        return float(lead.get("lead_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def priority_score(lead: Dict[str, Any]) -> int:
    """Return the numeric weight for a lead's priority."""

    return PRIORITY_ORDER.get(
        str(lead.get("priority", "") or ""),
        0,
    )


def rank_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return lead copies ranked by priority and score."""

    return sorted(
        (dict(lead) for lead in leads),
        key=lambda lead: (
            priority_score(lead),
            ranking_score(lead),
        ),
        reverse=True,
    )
