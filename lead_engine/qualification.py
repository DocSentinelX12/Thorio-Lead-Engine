from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from .router import ROUTES, score_routes


UNVERIFIED = "Unverified"
IN_REVIEW = "In Review"
QUALIFIED = "Qualified"
NOT_QUALIFIED = "Not Qualified"

VALID_STATUSES = {
    UNVERIFIED,
    IN_REVIEW,
    QUALIFIED,
    NOT_QUALIFIED,
}

# These windows are deliberately centralized and auditable. The repository
# previously had no explicit current-need/recent-inquiry window. They are
# therefore now part of the qualification contract rather than hidden in a
# scoring function.
CURRENT_NEED_DAYS = 30
RECENT_INQUIRY_DAYS = 30

INQUIRY_CONTEXT = re.compile(
    r"\b(?:inquir(?:y|ed|ies)|requested information|requested a quote|"
    r"requested pricing|requested a proposal|asked about|contacted us|"
    r"reached out|submitted an inquiry|submitted a request|"
    r"expressed interest|interested in|looking for|need(?:s|ed)?|"
    r"seeking|evaluating|considering|exploring)\b",
    re.IGNORECASE,
)



def validate_status(status: str) -> bool:
    return status in VALID_STATUSES


def _text(lead: Dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(key) or "")
        for key in (
            "company",
            "person",
            "signal",
            "signal_type",
            "job_title",
            "evidence",
        )
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recent_timestamp(lead: Dict[str, Any], *, days: int) -> str | None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    candidates = (
        "inquiry_at",
        "inquired_at",
        "last_inquiry_at",
        "last_contact_at",
        "updated_at",
        "discovered_at",
    )
    for key in candidates:
        parsed = _parse_datetime(lead.get(key))
        if parsed and cutoff <= parsed <= now:
            return parsed.isoformat()
    return None


def _current_need(lead: Dict[str, Any], route_scores: Dict[str, int]) -> Dict[str, Any]:
    text = _text(lead)
    active_route = any(route_scores.get(route, 0) > 0 for route in ROUTES)
    observed_at = _recent_timestamp(lead, days=CURRENT_NEED_DAYS)

    # A currently observed qualifying hiring/service signal is evidence of
    # need. We intentionally require a recent observation so stale webpages
    # or historical jobs cannot qualify a lead indefinitely.
    qualified = active_route and observed_at is not None
    return {
        "qualified": qualified,
        "observed_at": observed_at,
        "evidence": text.strip() if qualified else "",
        "reason": (
            "Recent qualifying business/hiring signal observed."
            if qualified
            else "No recent qualifying current-need signal was verified."
        ),
    }


def _recent_inquiry(lead: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(lead)
    has_inquiry_language = bool(INQUIRY_CONTEXT.search(text))
    observed_at = _recent_timestamp(lead, days=RECENT_INQUIRY_DAYS)
    qualified = has_inquiry_language and observed_at is not None

    return {
        "qualified": qualified,
        "observed_at": observed_at,
        "evidence": text.strip() if qualified else "",
        "reason": (
            "Recent inquiry/intent evidence was verified."
            if qualified
            else "No recent inquiry/intent evidence was verified."
        ),
    }


def _paxus_referral_checks(lead: Dict[str, Any], paxus_qualified: bool) -> Dict[str, Any]:
    checks = {
        "paxus_base_qualification": {
            "passed": paxus_qualified,
            "reason": "Paxus category plus current/recent intent requirement passed."
            if paxus_qualified
            else "Paxus base qualification did not pass.",
        },
        "company_verified": {
            "passed": bool(str(lead.get("company") or "").strip()),
            "reason": "Company is present." if lead.get("company") else "Company still requires research/verification.",
        },
        "named_hiring_contact": {
            "passed": bool(str(lead.get("contact_name") or lead.get("person") or "").strip()),
            "reason": "Named contact is present." if (lead.get("contact_name") or lead.get("person")) else "Relevant contact still requires research.",
        },
        "contact_communication": {
            "passed": lead.get("contact_communicated") is True,
            "reason": "Contact communication is recorded." if lead.get("contact_communicated") is True else "Contact communication has not been verified.",
        },
        "contact_consent": {
            "passed": lead.get("contact_consent") is True,
            "reason": "Contact consent is recorded." if lead.get("contact_consent") is True else "Contact consent has not been verified.",
        },
    }

    failures = [name for name, result in checks.items() if not result["passed"]]
    research_items = [
        name for name in (
            "company_verified",
            "named_hiring_contact",
        )
        if not checks[name]["passed"]
    ]
    verification_items = [
        name for name in (
            "contact_communication",
            "contact_consent",
        )
        if not checks[name]["passed"]
    ]

    return {
        "checks": checks,
        "passed": paxus_qualified and not failures,
        "failures": failures,
        "research_required": research_items,
        "verification_required": verification_items,
        "reason": (
            "All Paxus referral gates passed."
            if paxus_qualified and not failures
            else "Paxus is not yet a true referral; missing/failed checks are preserved for research or verification."
        ),
    }


def evaluate_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate Shiftr, Thorio and Paxus independently.

    A lead is never consumed by the first matching company. Every company
    gets its own category/intent decision and evidence record.

    Insufficient research is represented as research_required rather than
    silently converting a potentially valuable lead into a hard rejection.
    """
    if not isinstance(lead, dict):
        raise ValueError("lead must be a dictionary")

    scores = score_routes(
        company=str(lead.get("company") or ""),
        signal=str(lead.get("signal") or ""),
        evidence=str(lead.get("evidence") or ""),
    )
    current_need = _current_need(lead, scores)
    recent_inquiry = _recent_inquiry(lead)
    intent_passed = current_need["qualified"] or recent_inquiry["qualified"]

    results: Dict[str, Any] = {}
    for company in ROUTES:
        category_score = scores.get(company, 0)
        qualified = category_score > 0 and intent_passed
        results[company] = {
            "qualified": qualified,
            "category_score": category_score,
            "matched_category": category_score > 0,
            "current_need": current_need,
            "recent_inquiry": recent_inquiry,
            "reason": (
                "Matched an existing category and has current/recent intent evidence."
                if qualified
                else "Did not satisfy both an existing category and current/recent intent evidence."
            ),
            "qualification_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    paxus = results["Paxus"]
    paxus_referral = _paxus_referral_checks(lead, paxus["qualified"])
    paxus["true_referral"] = paxus_referral["passed"]
    paxus["referral_status"] = (
        "true_referral"
        if paxus_referral["passed"]
        else "research_required"
        if paxus["qualified"] and (
            paxus_referral["research_required"]
            or paxus_referral["verification_required"]
        )
        else "not_ready"
    )
    paxus["referral_checklist"] = paxus_referral

    return {
        "companies": results,
        "qualified_companies": [
            company
            for company in ROUTES
            if results[company]["qualified"]
        ],
        "paxus_true_referral": paxus_referral["passed"],
        "research_status": (
            "research_required"
            if any(
                results[company]["qualified"]
                and (
                    results[company].get("referral_status") == "research_required"
                )
                for company in ROUTES
            )
            else "complete"
        ),
    }


def apply_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Apply independent qualification results without deleting lead data."""
    updated = dict(lead)
    evaluation = evaluate_company_qualification(updated)
    updated["qualification_results"] = evaluation["companies"]
    updated["research_status"] = evaluation["research_status"]
    updated["potential_routes"] = evaluation["qualified_companies"]

    # Preserve legacy fields for existing consumers. They no longer act as
    # the sole source of truth for company qualification.
    updated["qualified"] = bool(evaluation["qualified_companies"])
    if evaluation["qualified_companies"]:
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["qualification_status"] = "qualified"
        updated["reason_not_qualified"] = ""
    else:
        updated["status"] = NOT_QUALIFIED
        updated["review_status"] = "Not Qualified"
        updated["qualification_status"] = "not_qualified"
        updated["reason_not_qualified"] = (
            "No company matched an existing category with current/recent intent evidence."
        )

    return updated


def qualify_lead(
    lead: Dict[str, object],
    *,
    qualified: bool,
    reason: str = "",
) -> Dict[str, object]:
    """Backward-compatible explicit human qualification decision."""
    if not isinstance(qualified, bool):
        raise ValueError("qualified must be explicitly True or False.")

    updated = dict(lead)
    if qualified:
        updated["qualified"] = True
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["qualification_status"] = "qualified"
        updated["reason_not_qualified"] = ""
    else:
        updated["qualified"] = False
        updated["status"] = NOT_QUALIFIED
        updated["review_status"] = "Not Qualified"
        updated["qualification_status"] = "not_qualified"
        updated["reason_not_qualified"] = reason
    return updated


def begin_review(lead: Dict[str, object]) -> Dict[str, object]:
    updated = dict(lead)
    updated["status"] = IN_REVIEW
    updated["review_status"] = "Review"
    updated["qualification_status"] = "in_review"
    return updated


if __name__ == "__main__":
    print("Qualification module loaded.")
