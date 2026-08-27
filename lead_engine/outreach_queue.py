from typing import Any, Dict, Iterable, List


ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
    "Review",
)


def build_outreach_queue(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Split processed leads into their final delivery queues.

    A lead is placed according to its existing route.
    Unknown or missing routes go to Review rather than being lost.
    """

    queues = {
        route_name: []
        for route_name in ROUTES
    }

    for lead in leads:
        route_name = str(
            lead.get("route", "Review")
        ).strip()

        if route_name not in queues:
            route_name = "Review"

        queues[route_name].append(lead)

    return queues


def summarize_queue(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of leads assigned to each delivery route.
    """

    queues = build_outreach_queue(leads)

    return {
        route_name: len(
            queues[route_name]
        )
        for route_name in ROUTES
    }


def get_route_leads(
    leads: Iterable[Dict[str, Any]],
    route_name: str,
) -> List[Dict[str, Any]]:
    """
    Return only leads assigned to the requested route.
    """

    queues = build_outreach_queue(leads)

    if route_name not in queues:
        return []

    return queues[route_name]
