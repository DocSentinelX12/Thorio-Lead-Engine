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


def group_leads_by_route(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group leads into every applicable route.

    A multi-route lead is included in every applicable
    route group rather than only its primary route.
    """

    groups: Dict[str, List[Dict[str, Any]]] = {}

    for lead in leads:
        routes = _lead_routes(lead)

        for route in routes:
            groups.setdefault(route, []).append(
                dict(lead)
            )

    return groups


def group_leads_by_company(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group leads by normalized company name."""

    groups: Dict[str, List[Dict[str, Any]]] = {}

    for lead in leads:
        company = str(
            lead.get("company", "") or ""
        ).strip()

        if not company:
            continue

        key = company.lower()

        groups.setdefault(key, []).append(
            dict(lead)
        )

    return groups
