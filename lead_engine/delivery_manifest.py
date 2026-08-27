from typing import Any, Dict, Iterable, List

from .delivery_gate import prepare_for_delivery
from .partner_export import prepare_partner_lead


PARTNER_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def _review_lead(
    lead: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    result = dict(lead)
    result["delivery_status"] = "review"
    result["delivery_reason"] = reason
    return result


def _approved_lead(
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

    Only leads that pass every delivery gate and have evidence supporting
    their assigned partner route are placed into partner queues.

    Leads that fail validation are placed into Review instead.
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
            manifest["Review"].append(
                _review_lead(
                    lead,
                    decision["reason"],
                )
            )
            continue

        route = decision["route"]

        if route not in PARTNER_ROUTES:
            manifest["Review"].append(
                _review_lead(
                    lead,
                    "unsupported_route",
                )
            )
            continue

        manifest[route].append(
            _approved_lead(
                decision["lead"],
            )
        )

    for route in PARTNER_ROUTES:
        manifest["counts"][route] = len(manifest[route])

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
