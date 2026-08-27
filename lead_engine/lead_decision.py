from __future__ import annotations

from typing import Any, Dict


DECISION_APPROVE = "approve"
DECISION_REVIEW = "review"
DECISION_REJECT = "reject"


def _score(lead: Dict[str, Any]) -> int:
    value = lead.get("lead_score", 0)

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _route(lead: Dict[str, Any]) -> str:
    return str(
        lead.get("route", "")
        or ""
    ).strip()


def _status(lead: Dict[str, Any]) -> str:
    return str(
        lead.get("status", "")
        or ""
    ).strip().lower()


def decide_lead(
    lead: Dict[str, Any],
) -> str:
    """
    Determine the operational decision for a lead.

    Approval requires:
    - a supported partner route
    - a qualifying score
    - a lifecycle status that is eligible for delivery

    Borderline or incomplete records go to review.
    Clearly invalid records are rejected.
    """

    route = _route(lead)
    score = _score(lead)
    status = _status(lead)

    if route not in {
        "Shiftr",
        "Paxus",
        "Thorio",
    }:
        return DECISION_REVIEW

    if status == "rejected":
        return DECISION_REJECT

    if score <= 0:
        return DECISION_REJECT

    if score < 50:
        return DECISION_REVIEW

    if status in {
        "",
        "new",
        "qualified",
        "approved",
    }:
        return DECISION_APPROVE

    if status == "delivered":
        return DECISION_REVIEW

    return DECISION_REVIEW


def apply_lead_decision(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a copy of a lead with its operational decision attached.
    """

    result = dict(lead)

    decision = decide_lead(
        result
    )

    result["decision"] = decision

    return result


def is_approved_lead(
    lead: Dict[str, Any],
) -> bool:
    return decide_lead(lead) == DECISION_APPROVE


def needs_lead_review(
    lead: Dict[str, Any],
) -> bool:
    return decide_lead(lead) == DECISION_REVIEW


def is_rejected_lead(
    lead: Dict[str, Any],
) -> bool:
    return decide_lead(lead) == DECISION_REJECT
