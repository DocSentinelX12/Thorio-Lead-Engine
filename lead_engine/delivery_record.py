from typing import Any, Dict


DELIVERY_FIELDS = (
    "delivery_status",
    "delivery_reason",
    "delivery_route",
)


def create_delivery_record(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a stable delivery record from a processed lead.

    The delivery decision is copied into a dedicated structure so
    downstream systems can persist and audit the exact decision
    without changing the original lead.
    """

    route = str(
        lead.get("route", "")
    ).strip()

    delivery_status = str(
        lead.get("delivery_status", "")
    ).strip()

    delivery_reason = str(
        lead.get("delivery_reason", "")
    ).strip()

    if delivery_status not in {
        "approved",
        "rejected",
        "review",
    }:
        delivery_status = (
            "approved"
            if route in {"Shiftr", "Paxus", "Thorio"}
            else "review"
        )

    return {
        "delivery_status": delivery_status,
        "delivery_reason": delivery_reason,
        "delivery_route": route,
    }


def apply_delivery_record(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a copy of the lead with its delivery decision
    normalized into persistent delivery fields.
    """

    result = dict(lead)

    record = create_delivery_record(
        result
    )

    result.update(record)

    return result
