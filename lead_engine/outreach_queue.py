from typing import Any, Dict, List


DELIVERY_ROUTES = {
    "Shiftr",
    "Paxus",
    "Thorio",
}


def build_outreach_queue(
    leads: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Organize qualified leads into the correct partner queue.

    A lead is only delivered when:
    - it has a supported route
    - it is qualified
    - it is not marked as a duplicate
    - it has a meaningful lead score
    """

    queues = {
        "Shiftr": [],
        "Paxus": [],
        "Thorio": [],
        "Review": [],
    }

    for lead in leads:
        route = str(
            lead.get("route", "")
        ).strip()

        qualified = lead.get(
            "qualified",
            True,
        )

        duplicate = lead.get(
            "possible_duplicate",
            False,
        )

        score = lead.get(
            "lead_score",
            0,
        )

        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 0

        if duplicate:
            queues["Review"].append(lead)
            continue

        if not qualified:
            queues["Review"].append(lead)
            continue

        if route not in DELIVERY_ROUTES:
            queues["Review"].append(lead)
            continue

        if score <= 0:
            queues["Review"].append(lead)
            continue

        queues[route].append(lead)

    return queues


def get_route_queue(
    leads: List[Dict[str, Any]],
    route: str,
) -> List[Dict[str, Any]]:
    """
    Return only qualified, deliverable leads for one route.
    """

    queues = build_outreach_queue(leads)

    return queues.get(
        route,
        [],
    )


def summarize_queue(
    leads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Return operational counts for the current lead queue.
    """

    queues = build_outreach_queue(leads)

    return {
        "total": len(leads),
        "shiftr": len(queues["Shiftr"]),
        "paxus": len(queues["Paxus"]),
        "thorio": len(queues["Thorio"]),
        "review": len(queues["Review"]),
  }
