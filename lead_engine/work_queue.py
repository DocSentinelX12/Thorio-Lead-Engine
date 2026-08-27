from typing import Any, Dict, List


PRIORITY_ORDER = {
    "High": 0,
    "Medium": 1,
    "Low": 2,
    "Review": 3,
}


def build_work_queue(
    leads: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build a deterministic human review queue.

    Higher-priority leads appear first.

    Qualified leads and explicitly rejected leads are excluded.
    Unverified and in-review leads remain available for human work.

    No outreach is performed automatically.
    """

    active = [
        lead
        for lead in leads
        if lead.get("qualified") is not True
        and lead.get("status") != "Not Qualified"
    ]

    return sorted(
        active,
        key=lambda lead: (
            PRIORITY_ORDER.get(
                lead.get("priority", "Review"),
                3,
            ),
            -(lead.get("lead_score") or 0),
            lead.get("company", "").lower(),
        ),
    )


def next_lead(
    leads: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    """
    Return the highest-priority lead requiring human work.
    """

    queue = build_work_queue(leads)

    return queue[0] if queue else None


if __name__ == "__main__":
    print(
        "Work queue loaded. "
        "Leads are prioritized for human review only."
    )
