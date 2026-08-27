from typing import Any, Dict

from .delivery_policy import is_delivery_ready
from .partner_rules import validate_partner_route


def evaluate_delivery_gate(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate whether a lead is eligible for partner delivery.

    This gate validates route, evidence, and delivery policy.
    Human approval is enforced at the final delivery boundary,
    not here, so leads can continue to be collected, qualified,
    routed, and stored while awaiting human approval.
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


def prepare_for_delivery(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
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
