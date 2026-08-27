from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .lead_decision import (
    DECISION_APPROVE,
    DECISION_REVIEW,
    decide_lead,
)


SUPPORTED_QUEUES = (
    "Shiftr",
    "Paxus",
    "Thorio",
    "Review",
)


def build_lead_queue(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Place leads into their operational queue.

    Approved leads go to their assigned partner.
    Review decisions go to Review.
    Rejected leads are excluded.
    """

    queues: Dict[str, List[Dict[str, Any]]] = {
        queue: []
        for queue in SUPPORTED_QUEUES
    }

    for lead in leads:
        decision = decide_lead(lead)
        route = str(
            lead.get("route", "")
            or ""
        ).strip()

        if decision == DECISION_APPROVE:
            if route in {
                "Shiftr",
                "Paxus",
                "Thorio",
            }:
                queues[route].append(dict(lead))

        elif decision == DECISION_REVIEW:
            queues["Review"].append(dict(lead))

    return queues


def queue_counts(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of leads in each operational queue.
    """

    queues = build_lead_queue(leads)

    return {
        queue: len(queues[queue])
        for queue in SUPPORTED_QUEUES
  }
