from typing import Any, Dict


DELIVERY_FIELDS = (
    "delivery_status",
    "delivery_reason",
    "delivery_route",
)

DELIVERY_STATES = {
    "approved",
    "rejected",
    "review",
    "queued",
    "attempting",
    "delivered",
    "failed",
    "retryable",
    "permanently_failed",
}


def create_delivery_record(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a stable delivery record from a processed lead.

    Missing or unrecognized state is fail-closed as review. A route
    alone is never sufficient evidence for approval.
    """

    route = str(lead.get("route", "") or "").strip()
    delivery_status = str(lead.get("delivery_status", "") or "").strip().lower()
    delivery_reason = str(lead.get("delivery_reason", "") or "").strip()

    if delivery_status not in DELIVERY_STATES:
        delivery_status = "review"
        if not delivery_reason:
            delivery_reason = "delivery_status_missing_or_unrecognized"

    return {
        "delivery_status": delivery_status,
        "delivery_reason": delivery_reason,
        "delivery_route": route,
    }


def apply_delivery_record(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a copy of the lead with normalized persistent delivery fields."""

    result = dict(lead)
    result.update(create_delivery_record(result))
    return result
