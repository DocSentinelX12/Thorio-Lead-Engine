from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from .router import ROUTES, score_routes

UNVERIFIED = "Unverified"
IN_REVIEW = "In Review"
QUALIFIED = "Qualified"
NOT_QUALIFIED = "Not Qualified"

VALID_STATUSES = {UNVERIFIED, IN_REVIEW, QUALIFIED, NOT_QUALIFIED}
CURRENT_NEED_DAYS = 30
RECENT_INQUIRY_DAYS = 30

INQUIRY_CONTEXT = re.compile(
    r"\b(?:inquir(?:y|ed|ies)|requested information|requested a quote|"
    r"requested pricing|requested a proposal|asked about|contacted us|"
    r"reached out|submitted an inquiry|submitted a request|"
    r"expressed interest|interested in|evaluating|considering|exploring)\b",
    re.IGNORECASE,
)

CURRENT_NEED_CONTEXT = re.compile(
    r"\b(?:hiring|hire|hiring for|recruiting|recruit|open(?:ing| role)?|"
    r"looking to hire|seeking (?:a |an )?(?:developer|engineer|designer|"
    r"product manager|data scientist|ai|ml|contractor|developer|engineer)|"
    r"need(?:s|ed)? (?:help )?(?:building|developing|integrating|creating)\b|"
    r"need(?:s|ed)? (?:a |an )?(?:developer|engineer|designer|product manager|"
    r"data scientist|ai|ml|contractor|developer|engineer|development team|"
    r"engineering team|software team)|staffing|recruitment support|"
    r"technology recruitment|development contractor|building (?:our|the) team|"
    r"growing (?:our|the) team|staff augmentation|outsourcing|outsource|"
    r"llm integration|ai agents?|saas development|mobile development)\b",
    re.IGNORECASE,
)

SHIFTR_SERVICE_NEED_CONTEXT = re.compile(
    r"\b(?:need(?:s|ed)?|want(?:s|ed)?|looking for|seeking|help with)\b"
    r".{0,80}\b(?:build(?:ing)?|develop(?:ing|ment)?|integrat(?:e|ing|ion)|"
    r"ai agents?|llm(?: integration)?|mobile development|saas development|"
    r"software development|development team|engineering team|staff augmentation|"
    r"outsourc(?:e|ed|ing)?)\b",
    re.IGNORECASE,
)


def validate_status(status: str) -> bool:
    return status in VALID_STATUSES


def _text(lead: Dict[str, Any]) -> str:
    return " ".join(str(lead.get(key) or "") for key in ("company", "person", "signal", "signal_type", "job_title", "evidence"))


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


def _recent_timestamp(lead: Dict[str, Any], *, days: int, fields: tuple[str, ...]) -> str | None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    for key in fields:
        parsed = _parse_datetime(lead.get(key))
        if parsed and cutoff <= parsed <= now:
            return parsed.isoformat()
    return None


def _observed_signal_timestamp(lead: Dict[str, Any]) -> str | None:
    return _recent_timestamp(lead, days=max(CURRENT_NEED_DAYS, RECENT_INQUIRY_DAYS), fields=("discovery_timestamp", "observed_at", "collected_at"))


def _current_need(lead: Dict[str, Any], route_scores: Dict[str, int]) -> Dict[str, Any]:
    text = _text(lead)
    has_need_language = bool(CURRENT_NEED_CONTEXT.search(text))
    observed_at = _recent_timestamp(lead, days=CURRENT_NEED_DAYS, fields=("need_at", "current_need_at", "hiring_need_at"))
    if has_need_language and observed_at is None:
        observed_at = _observed_signal_timestamp(lead)
    qualified = has_need_language and observed_at is not None
    return {"qualified": qualified, "observed_at": observed_at, "evidence": text.strip() if qualified else "", "reason": "Recent explicit current-need evidence was verified." if qualified else "No recent explicit current-need evidence was verified."}


def _recent_inquiry(lead: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(lead)
    has_inquiry_language = bool(INQUIRY_CONTEXT.search(text))
    observed_at = _recent_timestamp(lead, days=RECENT_INQUIRY_DAYS, fields=("inquiry_at", "inquired_at", "last_inquiry_at", "intent_at"))
    if has_inquiry_language and observed_at is None:
        observed_at = _observed_signal_timestamp(lead)
    qualified = has_inquiry_language and observed_at is not None
    return {"qualified": qualified, "observed_at": observed_at, "evidence": text.strip() if qualified else "", "reason": "Recent inquiry/intent evidence was verified." if qualified else "No recent inquiry/intent evidence was verified."}


def _paxus_referral_checks(lead: Dict[str, Any], paxus_qualified: bool) -> Dict[str, Any]:
    checks = {
        "paxus_base_qualification": {"passed": paxus_qualified, "reason": "Paxus category plus current/recent intent requirement passed." if paxus_qualified else "Paxus base qualification did not pass."},
        "company_verified": {"passed": bool(str(lead.get("company") or "").strip()), "reason": "Company is present." if lead.get("company") else "Company still requires research/verification."},
        "named_hiring_contact": {"passed": bool(str(lead.get("contact_name") or lead.get("person") or "").strip()), "reason": "Named contact is present." if (lead.get("contact_name") or lead.get("person")) else "Relevant contact still requires research."},
        "contact_communication": {"passed": lead.get("contact_communicated") is True, "reason": "Contact communication is recorded." if lead.get("contact_communicated") is True else "Contact communication has not been verified."},
        "contact_consent": {"passed": lead.get("contact_consent") is True, "reason": "Contact consent is recorded." if lead.get("contact_consent") is True else "Contact consent has not been verified."},
    }
    failures = [name for name, result in checks.items() if not result["passed"]]
    research_items = [name for name in ("company_verified", "named_hiring_contact") if not checks[name]["passed"]]
    verification_items = [name for name in ("contact_communication", "contact_consent") if not checks[name]["passed"]]
    return {"checks": checks, "passed": paxus_qualified and not failures, "failures": failures, "research_required": research_items, "verification_required": verification_items, "reason": "All Paxus referral gates passed." if paxus_qualified and not failures else "Paxus is not yet a true referral; missing/failed checks are preserved for research or verification."}


def evaluate_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(lead, dict):
        raise ValueError("lead must be a dictionary")
    company = str(lead.get("company") or "")
    signal = str(lead.get("signal") or "")
    evidence = str(lead.get("evidence") or "")
    text = _text(lead)
    scores = score_routes(company=company, signal=signal, evidence=evidence)
    current_need = _current_need(lead, scores)
    recent_inquiry = _recent_inquiry(lead)
    intent_passed = current_need["qualified"] or recent_inquiry["qualified"]
    results: Dict[str, Any] = {}
    for company_name in ROUTES:
        category_score = scores.get(company_name, 0)
        if company_name == "Shiftr" and SHIFTR_SERVICE_NEED_CONTEXT.search(text):
            category_score = max(category_score, 1)
        qualified = category_score > 0 and intent_passed
        results[company_name] = {"qualified": qualified, "category_score": category_score, "matched_category": category_score > 0, "current_need": current_need, "recent_inquiry": recent_inquiry, "reason": "Matched an existing category and has current/recent intent evidence." if qualified else "Did not satisfy both an existing category and current/recent intent evidence.", "qualification_timestamp": datetime.now(timezone.utc).isoformat()}
    paxus = results["Paxus"]
    paxus_referral = _paxus_referral_checks(lead, paxus["qualified"])
    paxus["true_referral"] = paxus_referral["passed"]
    paxus["referral_status"] = "true_referral" if paxus_referral["passed"] else "research_required" if paxus["qualified"] and (paxus_referral["research_required"] or paxus_referral["verification_required"]) else "not_ready"
    paxus["referral_checklist"] = paxus_referral
    return {"companies": results, "qualified_companies": [company_name for company_name in ROUTES if results[company_name]["qualified"]], "paxus_true_referral": paxus_referral["passed"], "research_status": "research_required" if paxus["qualified"] and paxus.get("referral_status") == "research_required" else "complete"}


def apply_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(lead)
    evaluation = evaluate_company_qualification(updated)
    updated["qualification_results"] = evaluation["companies"]
    updated["research_status"] = evaluation["research_status"]
    updated["potential_routes"] = evaluation["qualified_companies"]
    updated["qualified"] = bool(evaluation["qualified_companies"])
    if evaluation["qualified_companies"]:
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["qualification_status"] = "qualified"
        updated["review_state"] = "qualified"
        updated["reason_not_qualified"] = ""
    else:
        has_observed_evidence = bool(evaluation["companies"] and any(company_result["current_need"]["observed_at"] or company_result["recent_inquiry"]["observed_at"] for company_result in evaluation["companies"].values()))
        updated["qualified"] = False
        if has_observed_evidence:
            updated["status"] = IN_REVIEW
            updated["review_status"] = "Review"
            updated["qualification_status"] = "in_review"
            updated["review_state"] = "review"
            updated["reason_not_qualified"] = "Evidence exists but no company currently satisfies all qualification gates."
        else:
            updated["status"] = UNVERIFIED
            updated["review_status"] = "Review"
            updated["qualification_status"] = "unverified"
            updated["review_state"] = "review"
            updated["reason_not_qualified"] = "No current qualification decision is available; additional evidence is required."
    return updated


def qualify_lead(lead: Dict[str, object], *, qualified: bool, reason: str = "", business_need: str = "") -> Dict[str, object]:
    if not isinstance(qualified, bool):
        raise ValueError("qualified must be explicitly True or False.")
    updated = dict(lead)
    if business_need:
        updated["business_need"] = str(business_need).strip()
    if qualified:
        updated["qualified"] = True
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["qualification_status"] = "qualified"
        updated["review_state"] = "qualified"
        updated["reason_not_qualified"] = ""
    else:
        updated["qualified"] = False
        updated["status"] = NOT_QUALIFIED
        updated["review_status"] = "Not Qualified"
        updated["qualification_status"] = "not_qualified"
        updated["review_state"] = "rejected"
        updated["reason_not_qualified"] = reason
    return updated


def begin_review(lead: Dict[str, object]) -> Dict[str, object]:
    updated = dict(lead)
    updated["status"] = IN_REVIEW
    updated["review_status"] = "Review"
    updated["qualification_status"] = "in_review"
    updated["review_state"] = "review"
    return updated


if __name__ == "__main__":
    print("Qualification module loaded.")
