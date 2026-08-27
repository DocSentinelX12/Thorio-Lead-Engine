from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


PARTNER_ROUTES = {
    "Shiftr",
    "Paxus",
    "Thorio",
}

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


def _normalize_routes(lead: Dict[str, Any]) -> List[str]:
    routes = []

    raw_routes = lead.get("routes")

    if isinstance(raw_routes, str):
        raw_routes = [raw_routes]

    if isinstance(raw_routes, Iterable) and not isinstance(
        raw_routes, (str, bytes, dict)
    ):
        for route in raw_routes:
            route_name = str(route).strip()
            if route_name in PARTNER_ROUTES and route_name not in routes:
                routes.append(route_name)

    route = str(lead.get("route", "") or "").strip()

    if route in PARTNER_ROUTES and route not in routes:
        routes.append(route)

    delivery_route = str(
        lead.get("delivery_route", "") or ""
    ).strip()

    if delivery_route in PARTNER_ROUTES and delivery_route not in routes:
        routes.append(delivery_route)

    return routes


def approval_state(lead: Dict[str, Any]) -> str:
    value = str(
        lead.get("approval_status", "")
        or lead.get("human_approval_status", "")
        or ""
    ).strip().lower()

    if value in {
        APPROVAL_APPROVED,
        "human_approved",
        "approved_by_human",
    }:
        return APPROVAL_APPROVED

    if value in {
        APPROVAL_REJECTED,
        "human_rejected",
        "rejected_by_human",
    }:
        return APPROVAL_REJECTED

    if lead.get("human_approved") is True:
        return APPROVAL_APPROVED

    if lead.get("human_approved") is False:
        return APPROVAL_REJECTED

    return APPROVAL_PENDING


def mark_pending(lead: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(lead)

    result["approval_status"] = APPROVAL_PENDING
    result["human_approved"] = False
    result["approval_required"] = True

    routes = _normalize_routes(result)

    if routes:
        result["routes"] = routes

    return result


def approve_lead(
    lead: Dict[str, Any],
    approved_routes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    result = deepcopy(lead)

    existing_routes = _normalize_routes(result)

    if approved_routes is None:
        routes = existing_routes
    else:
        routes = []

        for route in approved_routes:
            route_name = str(route).strip()

            if (
                route_name in PARTNER_ROUTES
                and route_name in existing_routes
                and route_name not in routes
            ):
                routes.append(route_name)

    result["approval_status"] = APPROVAL_APPROVED
    result["human_approved"] = True
    result["approval_required"] = False
    result["approved_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    result["approved_routes"] = routes

    return result


def reject_lead(
    lead: Dict[str, Any],
    reason: str = "",
) -> Dict[str, Any]:
    result = deepcopy(lead)

    result["approval_status"] = APPROVAL_REJECTED
    result["human_approved"] = False
    result["approval_required"] = False
    result["rejection_reason"] = str(reason or "").strip()
    result["rejected_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    return result


def is_route_approved(
    lead: Dict[str, Any],
    route: str,
) -> bool:
    route_name = str(route or "").strip()

    if route_name not in PARTNER_ROUTES:
        return False

    if approval_state(lead) != APPROVAL_APPROVED:
        return False

    approved_routes = lead.get("approved_routes")

    if approved_routes is None:
        return route_name in _normalize_routes(lead)

    if isinstance(approved_routes, str):
        approved_routes = [approved_routes]

    return route_name in {
        str(value).strip()
        for value in approved_routes
    }


def delivery_authorized(
    lead: Dict[str, Any],
    route: Optional[str] = None,
) -> bool:
    if approval_state(lead) != APPROVAL_APPROVED:
        return False

    routes = _normalize_routes(lead)

    if not routes:
        return False

    if route is None:
        approved_routes = lead.get("approved_routes")

        if approved_routes is None:
            return True

        if isinstance(approved_routes, str):
            approved_routes = [approved_routes]

        return any(
            str(value).strip() in PARTNER_ROUTES
            for value in approved_routes
        )

    return is_route_approved(lead, route)


def filter_approved_for_route(
    leads: Iterable[Dict[str, Any]],
    route: str,
) -> List[Dict[str, Any]]:
    route_name = str(route or "").strip()

    if route_name not in PARTNER_ROUTES:
        return []

    return [
        deepcopy(lead)
        for lead in leads
        if delivery_authorized(lead, route_name)
    ]


def build_approval_queue(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    queue = []

    for lead in leads:
        if approval_state(lead) == APPROVAL_PENDING:
            queue.append(mark_pending(lead))

    return queue


def approval_summary(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = {
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "routes": {
            "Shiftr": 0,
            "Paxus": 0,
            "Thorio": 0,
        },
    }

    for lead in leads:
        state = approval_state(lead)
        summary[state] += 1

        if state == APPROVAL_APPROVED:
            for route in lead.get(
                "approved_routes",
                _normalize_routes(lead),
            ):
                if route in PARTNER_ROUTES:
                    summary["routes"][route] += 1

    return summary
