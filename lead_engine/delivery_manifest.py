from typing import Any, Dict, Iterable, List

from .delivery_gate import prepare_for_delivery
from .partner_export import prepare_partner_lead


PARTNER_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
    "Astrivon Labs",
)


def _review_lead(
    lead: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    result = dict(lead)
    result["delivery_status"] = "review"
    result["delivery_reason"] = reason
    return result


def _delivery_ready_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    result = prepare_partner_lead(lead)
    result["delivery_status"] = "approved"
    result["delivery_reason"] = ""
    return result


def build_delivery_manifest(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build the final delivery manifest.

    Every candidate route passes through the delivery gate before
    entering a partner queue.

    A lead may be delivered to multiple supported routes when those
    routes are explicitly present in eligible_routes, preserved_routes, or routes.

    Unsupported, rejected, or otherwise invalid routes are placed
    into Review.
    """

    manifest: Dict[str, Any] = {
        "Shiftr": [],
        "Paxus": [],
        "Thorio": [],
        "Astrivon Labs": [],
        "Review": [],
        "counts": {
            "Shiftr": 0,
            "Paxus": 0,
            "Thorio": 0,
            "Astrivon Labs": 0,
            "Review": 0,
        },
    }

    for lead in leads:
        eligible_routes = lead.get("eligible_routes")
        if eligible_routes is None:
            eligible_routes = lead.get("preserved_routes")

        if isinstance(eligible_routes, str):
            eligible_routes = [eligible_routes]

        if isinstance(eligible_routes, (list, tuple, set)):
            candidate_routes = [
                str(route).strip()
                for route in eligible_routes
                if str(route).strip()
            ]
        else:
            routes = lead.get("routes")

            if isinstance(routes, str):
                routes = [routes]

            if isinstance(routes, (list, tuple, set)):
                candidate_routes = [
                    str(route).strip()
                    for route in routes
                    if str(route).strip()
                ]
            else:
                route = str(
                    lead.get("route", "")
                    or ""
                ).strip()

                candidate_routes = (
                    [route]
                    if route
                    else []
                )

        if not candidate_routes:
            manifest["Review"].append(
                _review_lead(
                    dict(lead),
                    "unsupported_route",
                )
            )
            continue

        seen_routes = set()

        for route in candidate_routes:
            if route in seen_routes:
                continue

            seen_routes.add(route)

            if route not in PARTNER_ROUTES:
                manifest["Review"].append(
                    _review_lead(
                        dict(lead),
                        "unsupported_route",
                    )
                )
                continue

            route_lead = dict(lead)
            route_lead["route"] = route

            decision = prepare_for_delivery(
                route_lead
            )

            if not decision["approved"]:
                manifest["Review"].append(
                    _review_lead(
                        route_lead,
                        decision["reason"],
                    )
                )
                continue

            manifest[route].append(
                _delivery_ready_lead(
                    decision["lead"],
                )
            )

    for route in PARTNER_ROUTES:
        manifest["counts"][route] = len(
            manifest[route]
        )

    manifest["counts"]["Review"] = len(
        manifest["Review"]
    )

    return manifest


def delivery_ready_partner_leads(
    leads: Iterable[Dict[str, Any]],
    partner: str,
) -> List[Dict[str, Any]]:
    """Return only machine-verified, delivery-ready leads for one supported partner."""
    partner = str(partner or "").strip()
    if partner not in PARTNER_ROUTES:
        return []
    return build_delivery_manifest(leads)[partner]
