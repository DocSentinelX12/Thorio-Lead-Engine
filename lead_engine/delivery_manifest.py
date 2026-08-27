from typing import Any, Dict, Iterable, List

from .delivery_gate import prepare_for_delivery
from .partner_export import prepare_partner_lead


PARTNER_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def build_delivery_manifest(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build the final delivery manifest for processed leads.

    Every lead is evaluated through the delivery gate before it can
    appear in a partner queue. Rejected leads remain visible in the
    review queue with their rejection reason.
    """

    manifest: Dict[str, Any] = {
        "Shiftr": [],
        "Paxus": [],
        "Thorio": [],
        "Review": [],
        "counts": {
            "Shiftr": 0,
            "Paxus": 0,
            "Thorio": 0,
            "Review": 0,
        },
    }

    for lead in leads:
        decision = prepare_for_delivery(lead)

        if not decision["approved"]:
            review_lead = dict(lead)
            review_lead["delivery_status"] = "review"
            review_lead["delivery_reason"] = decision["reason"]

            manifest["Review"].append(review_lead)
            continue

        route = decision["route"]

        if route not in PARTNER_ROUTES:
            review_lead = dict(lead)
            review_lead["delivery_status"] = "review"
            review_lead["delivery_reason"] = "unsupported_route"

            manifest["Review"].append(review_lead)
            continue

        partner_lead = prepare_partner_lead(
            decision["lead"]
        )

        partner_lead["delivery_status"] = "approved"
        partner_lead["delivery_reason"] = ""

        manifest[route].append(partner_lead)

    for route in PARTNER_ROUTES:
        manifest["counts"][route] = len(
            manifest[route]
        )

    manifest["counts"]["Review"] = len(
        manifest["Review"]
    )

    return manifest


def approved_partner_leads(
    leads: Iterable[Dict[str, Any]],
    partner: str,
) -> List[Dict[str, Any]]:
    """
    Return only approved leads for one supported partner.
    """

    partner = str(partner or "").strip()

    if partner not in PARTNER_ROUTES:
        return []

    manifest = build_delivery_manifest(leads)

    return manifest[partner]
