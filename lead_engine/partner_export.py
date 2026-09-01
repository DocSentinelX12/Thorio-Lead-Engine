from typing import Any, Dict, Iterable, List

from .delivery_approval import delivery_authorized
from .delivery_gate import prepare_for_delivery


PARTNER_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def build_partner_exports(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build partner-specific exports only from leads that:

    1. pass the final delivery-quality gate, and
    2. have explicit human approval for the specific partner route.

    A lead may be exported to multiple approved partner routes.
    Unsupported, unqualified, pending, rejected, or otherwise
    unauthorized routes are never exported.
    """

    exports = {
        route: []
        for route in PARTNER_ROUTES
    }

    for lead in leads:
        approved_routes = lead.get("approved_routes")

        if isinstance(approved_routes, str):
            approved_routes = [approved_routes]

        if isinstance(approved_routes, (list, tuple, set)):
            candidate_routes = [
                str(route).strip()
                for route in approved_routes
                if str(route).strip() in PARTNER_ROUTES
            ]
        else:
            routes = lead.get("routes")

            if isinstance(routes, str):
                routes = [routes]

            if isinstance(routes, (list, tuple, set)):
                candidate_routes = [
                    str(route).strip()
                    for route in routes
                    if str(route).strip() in PARTNER_ROUTES
                ]
            else:
                route = str(
                    lead.get("route", "")
                    or ""
                ).strip()

                candidate_routes = (
                    [route]
                    if route in PARTNER_ROUTES
                    else []
                )

        seen_routes = set()

        for route in candidate_routes:
            if route in seen_routes:
                continue

            seen_routes.add(route)

            if not delivery_authorized(
                lead,
                route,
            ):
                continue

            route_lead = dict(lead)
            route_lead["route"] = route

            delivery_result = prepare_for_delivery(
                route_lead
            )

            if not delivery_result["approved"]:
                continue

            exports[route].append(
                prepare_partner_lead(
                    delivery_result["lead"]
                )
            )

    return exports


def prepare_partner_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize a lead into the stable partner export shape.
    """

    return {
        "source": lead.get("source", ""),
        "source_id": lead.get("source_id", ""),
        "url": lead.get("url", ""),
        "company": lead.get("company", ""),
        "person": lead.get("person", ""),
        "contact_name": lead.get(
            "contact_name",
            "",
        ),
        "contact_title": lead.get(
            "contact_title",
            "",
        ),
        "contact_email": lead.get(
            "contact_email",
            "",
        ),
        "signal": lead.get("signal", ""),
        "evidence": lead.get("evidence", ""),
        "route": lead.get("route", ""),
        "potential_routes": lead.get(
            "potential_routes",
            [],
        ),
        "lead_score": lead.get(
            "lead_score",
            0,
        ),
        "priority": lead.get(
            "priority",
            "",
        ),
        "status": lead.get(
            "status",
            "",
        ),
    }


def partner_export_summary(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of authorized, delivery-ready leads
    exported for each supported partner route.
    """

    exports = build_partner_exports(leads)

    return {
        partner: len(exports[partner])
        for partner in PARTNER_ROUTES
    }
