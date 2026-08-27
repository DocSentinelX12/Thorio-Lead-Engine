from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def filter_leads(
    leads: Iterable[Dict[str, Any]],
    *,
    route: Optional[str] = None,
    minimum_score: Optional[float] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Filter leads by route, score, and status.

    All supplied filters must match.
    Returned records are copies.
    """

    result: List[Dict[str, Any]] = []

    for lead in leads:
        if route is not None:
            if str(lead.get("route", "")).strip() != route:
                continue

        if minimum_score is not None:
            try:
                score = float(
                    lead.get("lead_score", 0)
                )
            except (TypeError, ValueError):
                score = 0

            if score < minimum_score:
                continue

        if status is not None:
            if str(lead.get("status", "")).strip() != status:
                continue

        result.append(dict(lead))

    return result


def filter_approved_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return leads currently approved for delivery."""

    return [
        dict(lead)
        for lead in leads
        if str(
            lead.get("delivery_status", "")
            or ""
        ).strip().lower()
        == "approved"
    ]
