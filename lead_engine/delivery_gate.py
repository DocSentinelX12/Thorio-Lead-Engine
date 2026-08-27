from typing import Any, Dict

from .delivery_policy import is_delivery_ready
from .partner_rules import validate_partner_route


def evaluate_delivery_gate(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Final safety gate before a lead can enter partner delivery.

    A lead must:
    1. Have a supported partner route.
    2. Have evidence that supports that assigned route.
    3. Meet the general delivery-quality requirements.

    Route validation happens first so unsupported routes receive the
    correct deterministic review reason.
    """

    route_result = validate_partner_route(lead)

    if not route_result["valid"]:
        return {
            "approved": False,
            "reason": route_result["reason"],
            "route": route_result["route"],
        }

    if not is_delivery_ready(lead):
        return {
            "approved": False,
            "reason": "delivery_policy_rejected",
            "route": route_result["route"],
        }

    return {
        "approved": True,
        "reason": "",
        "route": route_result["route"],
    }


def prepare_for_delivery(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a delivery decision without modifying the original lead.
    """

    result = evaluate_delivery_gate(lead)

    return {
        "approved": result["approved"],
        "reason": result["reason"],
        "route": result["route"],
        "lead": dict(lead) if result["approved"] else None,
    }
