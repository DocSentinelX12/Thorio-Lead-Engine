from typing import Any, Dict, List

from .delivery_gate import evaluate_delivery_gate


PARTNER_ROUTES = ("Shiftr", "Paxus", "Thorio")


def deliverable_partner(lead: Dict[str, Any]) -> str:
    """
    Return the partner that should receive a lead.

    The delivery gate is authoritative. Leads that fail the gate
    are never assigned to a partner.
    """

    gate = evaluate_delivery_gate(lead)

    if not gate["approved"]:
        return ""

    route = gate["route"]

    if route not in PARTNER_ROUTES:
        return ""

    return route


def partition_leads(
    leads: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Separate approved leads into partner-specific delivery queues.

    Rejected or unsupported leads are placed in the Review queue.
    """

    result: Dict[str, List[Dict[str, Any]]] = {
        "Shiftr": [],
        "Paxus": [],
        "Thorio": [],
        "Review": [],
    }

    for lead in leads:
        partner = deliverable_partner(lead)

        if partner:
            result[partner].append(dict(lead))
        else:
            result["Review"].append(dict(lead))

    return result


def delivery_counts(
    leads: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return delivery counts by partner and review queue.
    """

    partitioned = partition_leads(leads)

    return {
        "Shiftr": len(partitioned["Shiftr"]),
        "Paxus": len(partitioned["Paxus"]),
        "Thorio": len(partitioned["Thorio"]),
        "Review": len(partitioned["Review"]),
    }
