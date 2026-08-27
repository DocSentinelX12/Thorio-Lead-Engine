from typing import Any, Dict, Iterable, List

from .delivery_policy import (
    delivery_rejection_reason,
    is_delivery_ready,
)


SUPPORTED_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def build_delivery_batches(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group delivery-ready leads into partner-specific batches.

    A lead must satisfy the delivery policy before it can be
    placed into a partner delivery batch.
    """

    batches: Dict[str, List[Dict[str, Any]]] = {
        route: []
        for route in SUPPORTED_ROUTES
    }

    for lead in leads:
        route = str(
            lead.get("route", "")
            or ""
        ).strip()

        if route not in SUPPORTED_ROUTES:
            continue

        if not is_delivery_ready(lead):
            continue

        batches[route].append(
            dict(lead)
        )

    return batches


def delivery_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of delivery-ready leads for each partner.
    """

    batches = build_delivery_batches(leads)

    return {
        route: len(batches[route])
        for route in SUPPORTED_ROUTES
    }


def rejected_delivery_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Return leads that cannot currently be delivered.

    Each rejected lead receives a delivery_reason explaining
    the policy failure.
    """

    rejected: List[Dict[str, Any]] = []

    for lead in leads:
        route = str(
            lead.get("route", "")
            or ""
        ).strip()

        if route in SUPPORTED_ROUTES and is_delivery_ready(lead):
            continue

        item = dict(lead)

        reason = delivery_rejection_reason(
            item
        )

        item["delivery_reason"] = (
            reason
            or "delivery_policy_rejected"
        )

        rejected.append(item)

    return rejected
