from typing import Any, Dict, Iterable, List


SUPPORTED_ROUTES = ("Shiftr", "Paxus", "Thorio")


def build_delivery_batches(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group qualified leads into partner-specific delivery batches.

    Only supported partner routes are included. Review and unknown routes
    are excluded from delivery.
    """

    batches: Dict[str, List[Dict[str, Any]]] = {
        route: []
        for route in SUPPORTED_ROUTES
    }

    for lead in leads:
        route = str(lead.get("route", "")).strip()

        if route not in SUPPORTED_ROUTES:
            continue

        batches[route].append(dict(lead))

    return batches


def delivery_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of deliverable leads for each partner.
    """

    batches = build_delivery_batches(leads)

    return {
        route: len(batches[route])
        for route in SUPPORTED_ROUTES
    }
