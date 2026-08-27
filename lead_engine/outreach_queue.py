from typing import Any, Dict, Iterable, List

from .delivery_manifest import build_delivery_manifest


ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
    "Review",
)


def build_outreach_queue(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build the final outreach queues from the delivery manifest.

    The delivery manifest is authoritative. Every lead therefore
    passes the same route validation, evidence validation, score
    threshold, and delivery-quality checks before entering a
    partner outreach queue.

    Rejected, unsupported, or mismatched leads remain in Review.
    """

    manifest = build_delivery_manifest(
        list(leads)
    )

    return {
        route_name: list(
            manifest.get(route_name, [])
        )
        for route_name in ROUTES
    }


def summarize_queue(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of leads in each final outreach queue.
    """

    queues = build_outreach_queue(
        list(leads)
    )

    return {
        route_name: len(
            queues[route_name]
        )
        for route_name in ROUTES
    }


def get_route_leads(
    leads: Iterable[Dict[str, Any]],
    route_name: str,
) -> List[Dict[str, Any]]:
    """
    Return only the leads that actually passed the delivery
    gate for the requested partner route.

    Review and unsupported route names never return partner
    leads.
    """

    route_name = str(
        route_name or ""
    ).strip()

    if route_name not in ROUTES:
        return []

    queues = build_outreach_queue(
        list(leads)
    )

    return queues[route_name]
