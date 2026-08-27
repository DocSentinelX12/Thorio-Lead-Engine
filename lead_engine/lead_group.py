from __future__ import annotations

from typing import Any, Dict, Iterable, List


def group_leads_by_route(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group leads by their assigned route."""

    groups: Dict[str, List[Dict[str, Any]]] = {}

    for lead in leads:
        route = str(
            lead.get("route", "") or ""
        ).strip()

        if not route:
            continue

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
