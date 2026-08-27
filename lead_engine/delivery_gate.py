from typing import Any, Dict

from .delivery_policy import is_delivery_ready
from .partner_rules import validate_partner_route


APPROVAL_STATUSES = {
    "approved",
    "human_approved",
}


def _is_human_approved(lead: Dict[str, Any]) -> bool:
    """
    Return True only when the lead carries an explicit human approval.

    Automatic qualification, scoring, routing, or preparation does
    not constitute delivery approval.
    """

    if lead.get("human_approved") is True:
        return True

    approval_status = str(
        lead.get("approval_status", "")
        or ""
    ).strip().lower()

    return approval_status in APPROVAL_STATUSES


def evaluate_delivery_gate(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Final safety gate before a lead can enter partner delivery.

    A lead must:
    1. Have explicit human approval.
    2. Have a supported partner route.
    3. Have evidence supporting that route.
    4. Meet the general delivery-quality requirements.

    Human approval is checked first so no automated pipeline state
    can accidentally authorize delivery.
    """

    if not _is_human_approved(lead):
        return {
            "approved": False,
            "reason": "human_approval_required",
            "route": lead.get("route", ""),
        }

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
