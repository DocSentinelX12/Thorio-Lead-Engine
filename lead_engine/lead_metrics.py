from __future__ import annotations

from typing import Any, Dict, Iterable


def lead_metrics(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Calculate simple lead-quality metrics."""

    records = list(leads)

    total = len(records)
    scored = 0
    score_total = 0.0
    high_priority = 0

    for lead in records:
        raw_score = lead.get("lead_score")

        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0

        if raw_score is not None:
            scored += 1
            score_total += score

        priority = str(
            lead.get("priority", "") or ""
        ).strip().lower()

        if priority == "high":
            high_priority += 1

    average_score = (
        score_total / scored
        if scored
        else 0.0
    )

    return {
        "total": total,
        "scored": scored,
        "average_score": average_score,
        "high_priority": high_priority,
    }
