from __future__ import annotations

from typing import Any, Dict


PRIORITY_THRESHOLDS = {
    "critical": 90,
    "high": 75,
    "medium": 50,
    "low": 0,
}


def priority_for_score(score: Any) -> str:
    """Return the priority associated with a lead score."""

    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0

    if value >= PRIORITY_THRESHOLDS["critical"]:
        return "Critical"

    if value >= PRIORITY_THRESHOLDS["high"]:
        return "High"

    if value >= PRIORITY_THRESHOLDS["medium"]:
        return "Medium"

    return "Low"


def assign_priority(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a copy of a lead with priority assigned from its score."""

    result = dict(lead)
    result["priority"] = priority_for_score(
        result.get("lead_score", 0)
    )

    return result
