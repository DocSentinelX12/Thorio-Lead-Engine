from __future__ import annotations

from typing import Any, Dict, Iterable


def average_score(
    leads: Iterable[Dict[str, Any]],
) -> float:
    """Return the average numeric lead score."""

    scores = []

    for lead in leads:
        try:
            scores.append(float(lead.get("lead_score", 0)))
        except (TypeError, ValueError):
            continue

    if not scores:
        return 0.0

    return sum(scores) / len(scores)


def highest_score(
    leads: Iterable[Dict[str, Any]],
) -> float:
    """Return the highest numeric lead score."""

    scores = []

    for lead in leads:
        try:
            scores.append(float(lead.get("lead_score", 0)))
        except (TypeError, ValueError):
            continue

    return max(scores, default=0.0)


def lowest_score(
    leads: Iterable[Dict[str, Any]],
) -> float:
    """Return the lowest numeric lead score."""

    scores = []

    for lead in leads:
        try:
            scores.append(float(lead.get("lead_score", 0)))
        except (TypeError, ValueError):
            continue

    return min(scores, default=0.0)
