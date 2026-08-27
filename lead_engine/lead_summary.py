from __future__ import annotations

from typing import Any, Dict, Iterable


def summarize_leads(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return a compact summary of a lead collection."""

    records = list(leads)

    routes: Dict[str, int] = {}
    statuses: Dict[str, int] = {}
    priorities: Dict[str, int] = {}

    for lead in records:
        route = str(lead.get("route", "") or "").strip()
        status = str(lead.get("status", "") or "").strip()
        priority = str(
            lead.get("priority", "") or ""
        ).strip()

        if route:
            routes[route] = routes.get(route, 0) + 1

        if status:
            statuses[status] = statuses.get(status, 0) + 1

        if priority:
            priorities[priority] = priorities.get(priority, 0) + 1

    return {
        "total": len(records),
        "routes": routes,
        "statuses": statuses,
        "priorities": priorities,
    }
