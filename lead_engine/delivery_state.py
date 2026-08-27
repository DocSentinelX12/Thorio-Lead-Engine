from typing import Any, Dict


DELIVERY_STATES = (
    "pending",
    "approved",
    "rejected",
    "review",
    "delivered",
    "failed",
)


def normalize_delivery_state(value: Any) -> str:
    """
    Normalize a delivery state into a supported state.

    Unknown or empty values become pending.
    """

    state = str(value or "").strip().lower()

    if state in DELIVERY_STATES:
        return state

    return "pending"


def set_delivery_state(
    lead: Dict[str, Any],
    state: str,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Return a copy of a lead with its delivery state updated.

    Existing lead data is preserved.
    """

    result = dict(lead)

    result["delivery_status"] = normalize_delivery_state(
        state
    )
    result["delivery_reason"] = str(
        reason or ""
    ).strip()

    return result


def is_delivery_complete(
    lead: Dict[str, Any],
) -> bool:
    """
    Return True when the lead has reached a terminal
    delivery state.
    """

    return normalize_delivery_state(
        lead.get("delivery_status")
    ) in {
        "delivered",
        "failed",
    }


def is_ready_for_delivery(
    lead: Dict[str, Any],
) -> bool:
    """
    Return True only when the lead has been explicitly
    approved for delivery and has a supported partner route.
    """

    status = normalize_delivery_state(
        lead.get("delivery_status")
    )

    route = str(
        lead.get("route", "")
    ).strip()

    return (
        status == "approved"
        and route in {
            "Shiftr",
            "Paxus",
            "Thorio",
        }
  )
