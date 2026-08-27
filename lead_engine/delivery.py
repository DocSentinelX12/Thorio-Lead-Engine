from typing import Any, Dict, Iterable, List


SUPPORTED_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def _lead_routes(lead: Dict[str, Any]) -> List[str]:
    """
    Return every supported route applicable to the lead.

    potential_routes is authoritative when present. The legacy
    single route field remains supported for compatibility.
    """

    potential_routes = lead.get("potential_routes")

    if potential_routes:
        routes = []

        for route in potential_routes:
            route_name = str(route or "").strip()

            if (
                route_name in SUPPORTED_ROUTES
                and route_name not in routes
            ):
                routes.append(route_name)

        return routes

    route = str(
        lead.get("route", "")
        or ""
    ).strip()

    if route in SUPPORTED_ROUTES:
        return [route]

    return []


def build_delivery_batches(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group prepared leads into every applicable partner batch.

    A lead may appear in one, two, or all three partner batches.
    It is never removed from consideration because another route
    was also selected.
    """

    batches: Dict[str, List[Dict[str, Any]]] = {
        route: []
        for route in SUPPORTED_ROUTES
    }

    for lead in leads:
        for route in _lead_routes(lead):
            batches[route].append(dict(lead))

    return batches


def delivery_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of applicable delivery routes.
    """

    batches = build_delivery_batches(leads)

    return {
        route: len(batches[route])
        for route in SUPPORTED_ROUTES
    }
