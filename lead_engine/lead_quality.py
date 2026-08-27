from __future__ import annotations

from typing import Any, Dict, Iterable, List


def quality_score(lead: Dict[str, Any]) -> float:
    """Calculate a simple data-quality score from 0 to 100."""

    checks = (
        bool(str(lead.get("company", "") or "").strip()),
        bool(str(lead.get("source", "") or "").strip()),
        bool(str(lead.get("source_id", "") or "").strip()),
        bool(str(lead.get("url", "") or "").strip()),
        bool(str(lead.get("signal", "") or "").strip()),
        bool(str(lead.get("evidence", "") or "").strip()),
        bool(str(lead.get("contact_email", "") or "").strip()),
    )

    return round(
        sum(checks) / len(checks) * 100,
        2,
    )


def is_high_quality(
    lead: Dict[str, Any],
    minimum_score: float = 70,
) -> bool:
    """Return True when the lead meets the quality threshold."""

    return quality_score(lead) >= minimum_score


def filter_high_quality(
    leads: Iterable[Dict[str, Any]],
    minimum_score: float = 70,
) -> List[Dict[str, Any]]:
    """Return copies of leads meeting the quality threshold."""

    return [
        dict(lead)
        for lead in leads
        if is_high_quality(lead, minimum_score)
    ]
