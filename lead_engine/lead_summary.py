from __future__ import annotations

from typing import Any, Dict, Iterable


def summarize_leads(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return basic operational summary statistics for a lead collection."""

    records = list(leads)

    routes: Dict[str, int] = {}
    statuses: Dict[str, int] = {}
    approved = 0

    for lead in records:
        route = str(lead.get("route", "") or "").strip()
        status = str(lead.get("status", "") or "").strip()

        if route:
            routes[route] = routes.get(route, 0) + 1

        if status:
            statuses[status] = statuses.get(status, 0) + 1

        if (
            str(
                lead.get("delivery_status", "") or ""
            ).strip().lower()
            == "approved"
        ):
            approved += 1

    return {
        "total": len(records),
        "approved": approved,
        "routes": routes,
        "statuses": statuses,
    }
