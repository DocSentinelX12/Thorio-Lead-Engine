from typing import Any, Dict


DELIVERY_STATES = (
    "pending",
    "approved",
    "rejected",
    "review",
    "delivered",
    "failed",
)


TERMINAL_STATES = {
    "delivered",
    "failed",
}


SUPPORTED_ROUTES = {
    "Shiftr",
    "Paxus",
    "Thorio",
}


def normalize_delivery_state(value: Any) -> str:
    """
    Normalize delivery state into the single authoritative
    delivery-state vocabulary.
    """

    state = str(value or "").strip().lower()

    if state in DELIVERY_STATES:
        return state

    return "pending"


def get_delivery_state(
    lead: Dict[str, Any],
) -> str:
    """
    Return the authoritative delivery state for a lead.
    """

    return normalize_delivery_state(
        lead.get("delivery_status")
    )


def set_delivery_state(
    lead: Dict[str, Any],
    state: str,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Return a copy of a lead with its authoritative delivery
    state and reason updated.
    """

    result = dict(lead)

    normalized = normalize_delivery_state(state)

    result["delivery_status"] = normalized
    result["delivery_reason"] = str(
        reason or ""
    ).strip()

    return result


def is_delivery_complete(
    lead: Dict[str, Any],
) -> bool:
    """
    Return True only when delivery has reached a terminal state.
    """

    return get_delivery_state(lead) in TERMINAL_STATES


def is_ready_for_delivery(
    lead: Dict[str, Any],
) -> bool:
    """
    Return True only when the authoritative delivery state is
    approved and the lead has a supported partner route.
    """

    if get_delivery_state(lead) != "approved":
        return False

    route = str(
        lead.get("route", "")
    ).strip()

    return route in SUPPORTED_ROUTES
