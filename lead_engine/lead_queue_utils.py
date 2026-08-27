from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_ranking import rank_leads


def queue_ready_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Return leads that are ready to enter the outreach queue.

    A lead is queue-ready when it has:
    - a company
    - a route
    - an approved delivery status
    - a usable contact email
    """

    ready = []

    for lead in leads:
        company = str(lead.get("company", "") or "").strip()
        route = str(lead.get("route", "") or "").strip()
        delivery_status = str(
            lead.get("delivery_status", "") or ""
        ).strip().lower()
        email = str(
            lead.get("contact_email", "") or ""
        ).strip()

        if (
            company
            and route
            and delivery_status == "approved"
            and email
        ):
            ready.append(dict(lead))

    return rank_leads(ready)


def queue_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """Return counts of queue-ready leads by route."""

    counts: Dict[str, int] = {}

    for lead in queue_ready_leads(leads):
        route = str(lead.get("route", "") or "").strip()

        if route:
            counts[route] = counts.get(route, 0) + 1

    return counts
