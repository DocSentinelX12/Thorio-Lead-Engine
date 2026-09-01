from __future__ import annotations

from typing import Any, Dict, Iterable, List


SUPPORTED_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def _lead_routes(
    lead: Dict[str, Any],
) -> List[str]:
    """
    Return every supported route applicable to the lead.

    potential_routes is authoritative when present.
    The legacy single route field remains supported
    for compatibility.
    """

    potential_routes = lead.get("potential_routes")

    if isinstance(potential_routes, str):
        potential_routes = [potential_routes]

    if isinstance(potential_routes, list):
        routes = []

        for route in potential_routes:
            route_name = str(route or "").strip()

            if (
                route_name in SUPPORTED_ROUTES
                and route_name not in routes
            ):
                routes.append(route_name)

        if routes:
            return routes

    route = str(
        lead.get("route", "")
        or ""
    ).strip()

    if route in SUPPORTED_ROUTES:
        return [route]

    return []


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
    """
    Return leads applicable to the requested route.

    Multi-route leads are included in every route listed
    in potential_routes. The legacy single route field
    remains supported for compatibility.
    """

    requested_route = str(route).strip().lower()

    return [
        dict(lead)
        for lead in leads
        if any(
            route_name.lower() == requested_route
            for route_name in _lead_routes(lead)
        )
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
