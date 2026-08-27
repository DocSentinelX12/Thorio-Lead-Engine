from __future__ import annotations

from typing import Any, Dict, Iterable, List


def filter_by_min_score(
    leads: Iterable[Dict[str, Any]],
    minimum_score: float,
) -> List[Dict[str, Any]]:
    """Return leads whose score meets or exceeds the minimum."""

    result: List[Dict[str, Any]] = []

    for lead in leads:
        try:
            score = float(lead.get("lead_score", 0))
        except (TypeError, ValueError):
            continue

        if score >= minimum_score:
            result.append(dict(lead))

    return result


def filter_by_route(
    leads: Iterable[Dict[str, Any]],
    route: str,
) -> List[Dict[str, Any]]:
    """Return leads assigned to the requested route."""

    requested_route = str(route).strip().lower()

    return [
        dict(lead)
        for lead in leads
        if str(lead.get("route", "")).strip().lower()
        == requested_route
    ]


def filter_by_status(
    leads: Iterable[Dict[str, Any]],
    status: str,
) -> List[Dict[str, Any]]:
    """Return leads matching the requested status."""

    requested_status = str(status).strip().lower()

    return [
        dict(lead)
        for lead in leads
        if str(lead.get("status", "")).strip().lower()
        == requested_status
    ]
