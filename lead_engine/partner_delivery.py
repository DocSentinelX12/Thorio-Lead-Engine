from typing import Any, Dict, Iterable, List

from .delivery import build_delivery_batches


PARTNER_ORDER = ("Shiftr", "Paxus", "Thorio")


def prepare_partner_delivery(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Prepare qualified leads for partner-specific delivery.

    Review leads and unsupported routes are excluded by the delivery layer.
    """

    batches = build_delivery_batches(leads)

    return {
        partner: list(batches.get(partner, []))
        for partner in PARTNER_ORDER
    }


def partner_delivery_summary(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Return delivery counts plus the overall number of deliverable leads.
    """

    batches = prepare_partner_delivery(leads)

    counts = {
        partner: len(batches[partner])
        for partner in PARTNER_ORDER
    }

    return {
        "counts": counts,
        "total": sum(counts.values()),
    }
