from typing import Any, Dict, Iterable, List

from .partner_export import (
    PARTNER_ROUTES,
    build_partner_exports,
)


def build_delivery_batches(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build the final delivery batches for each partner.

    Only explicitly routed partner leads are delivered.
    Review and unknown routes are excluded.
    """

    exports = build_partner_exports(leads)

    return {
        partner: list(exports.get(partner, []))
        for partner in PARTNER_ROUTES
    }


def delivery_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of leads ready for delivery to each partner.
    """

    batches = build_delivery_batches(leads)

    return {
        partner: len(batches[partner])
        for partner in PARTNER_ROUTES
    }


def total_deliverable_leads(
    leads: Iterable[Dict[str, Any]],
) -> int:
    """
    Return the total number of partner-deliverable leads.
    """

    counts = delivery_counts(leads)

    return sum(counts.values())
