from __future__ import annotations

from typing import Any, Dict, Iterable, List


SUPPORTED_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def _get_routes(
    lead: Dict[str, Any],
) -> List[str]:
    potential = lead.get(
        "potential_routes"
    )

    if isinstance(potential, list):
        routes = [
            str(route).strip()
            for route in potential
            if str(route).strip() in SUPPORTED_ROUTES
        ]

        if routes:
            return routes

    route = str(
        lead.get("route", "") or ""
    ).strip()

    if route in SUPPORTED_ROUTES:
        return [route]

    return []


def route_leads(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group leads into every applicable supported route.

    potential_routes is authoritative when present.
    The legacy single route field remains supported
    for compatibility.
    """

    result: Dict[str, List[Dict[str, Any]]] = {
        route: []
        for route in SUPPORTED_ROUTES
    }

    result["Review"] = []

    for lead in leads:
        routes = _get_routes(lead)

        if not routes:
            result["Review"].append(
                dict(lead)
            )
            continue

        for route in routes:
            result[route].append(
                dict(lead)
            )

    return result


def route_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return counts for each supported route plus Review.
    """

    routed = route_leads(leads)

    return {
        route: len(records)
        for route, records in routed.items()
    }
