from __future__ import annotations

from typing import Any, Dict, Iterable, List


SUPPORTED_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def route_leads(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group leads into supported routes and Review."""

    result: Dict[str, List[Dict[str, Any]]] = {
        route: []
        for route in SUPPORTED_ROUTES
    }
    result["Review"] = []

    for lead in leads:
        route = str(
            lead.get("route", "") or ""
        ).strip()

        if route in SUPPORTED_ROUTES:
            result[route].append(dict(lead))
        else:
            result["Review"].append(dict(lead))

    return result


def route_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """Return counts for each supported route plus Review."""

    routed = route_leads(leads)

    return {
        route: len(records)
        for route, records in routed.items()
    }
