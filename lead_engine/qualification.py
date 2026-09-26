from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from .router import ROUTES, score_routes
from .astrivon_referral import match_astrivon_services

UNVERIFIED = "Unverified"
IN_REVIEW = "In Review"
QUALIFIED = "Qualified"
NOT_QUALIFIED = "Not Qualified"
VALID_STATUSES = {UNVERIFIED, IN_REVIEW, QUALIFIED, NOT_QUALIFIED}
CURRENT_NEED_DAYS = 30
RECENT_INQUIRY_DAYS = 30

INQUIRY_CONTEXT = re.compile(r"\b(?:inquir(?:y|ed|ies)|requested information|requested a quote|requested pricing|requested a proposal|asked about|contacted us|reached out|submitted an inquiry|submitted a request|expressed interest|interested in|evaluating|considering|exploring)\b", re.I)
CURRENT_NEED_CONTEXT = re.compile(r"\b(?:hiring|hire|hiring for|recruiting|recruit|opening|open role|looking to hire|seeking|staffing|recruitment support|technology recruitment|development contractor|staff augmentation|outsourcing|outsource|llm integration|ai agents?|saas development|mobile development|software development|engineering team|development team|dev agency|tech partner|mvp|b2b outreach|b2b sales|lead generation|sales automation|computer vision|business workflow|crm automation|scaling my web|seed funding|non-technical founder)\b", re.I)
SHIFTR_SERVICE_NEED_CONTEXT = re.compile(r"\b(?:need(?:s|ed)?|want(?:s|ed)?|looking for|seeking|help with)\b.{0,120}\b(?:build(?:ing)?|develop(?:ing|ment)?|integrat(?:e|ing|ion)|ai agents?|llm(?: integration)?|mobile development|saas development|software development|development team|engineering team|staff augmentation|outsourc(?:e|ed|ing)?)\b", re.I)


def validate_status(status: str) -> bool:
    return status in VALID_STATUSES


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


def _recent_timestamp(value: Any, days: int) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    now = datetime.now(timezone.utc)
    if now - timedelta(days=days) <= parsed <= now:
        return parsed.isoformat()
    return None


def _research_sections(lead: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    sections: Dict[str, Dict[str, Any]] = {}
    for key in ("business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research", "route_research"):
        value = lead.get(key)
        if isinstance(value, dict):
            sections[key] = value
    return sections


def _section_verified(section: Dict[str, Any]) -> bool:
    status = str(section.get("verification_status") or section.get("status") or "").strip().lower()
    return section.get("verified") is True or status in {"verified", "research_verified", "complete"}


def _verified_research_text(lead: Dict[str, Any], route: str | None = None) -> str:
    """Return verified research text without leaking another route's evidence."""
    sections = _research_sections(lead)
    verified_parts: list[str] = []
    for key, section in sections.items():
        if key == "route_research":
            routes = section.get("routes")
            if isinstance(routes, dict) and route:
                route_item = routes.get(route)
                if isinstance(route_item, dict) and _section_verified(route_item):
                    for field in ("evidence", "business_need", "current_need", "need", "service_need", "requirement", "role", "description", "intent"):
                        value = route_item.get(field)
                        if isinstance(value, str) and value.strip():
                            verified_parts.append(value.strip())
                continue
        if not _section_verified(section):
            continue
        for field in ("business_need", "current_need", "recent_inquiry", "need", "service_need", "requirement", "role", "description", "intent"):
            value = section.get(field)
            if isinstance(value, str) and value.strip():
                verified_parts.append(value.strip())
    return " ".join(verified_parts)


def _verified_intent(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Require recent evidence from the verified research itself, including nested evidence events."""
    sections = _research_sections(lead)
    candidates = []
    for key in ("current_intent_research", "business_need_research", "route_research"):
        section = sections.get(key)
        if not section or not _section_verified(section):
            continue
        for field in ("current_need", "recent_inquiry", "business_need", "need", "intent"):
            value = section.get(field)
            if isinstance(value, str) and value.strip():
                candidates.append((field, value.strip(), section))
        evidence = section.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                item_status = str(item.get("verification_status") or item.get("status") or "").strip().lower()
                if item_status not in {"verified", "research_verified", "complete"}:
                    continue
                item_value = str(item.get("evidence") or item.get("signal") or "").strip()
                if item_value:
                    candidates.append(("evidence", item_value, item))
    timestamp_keys = ("observed_at", "need_at", "current_need_at", "hiring_need_at", "inquiry_at", "inquired_at", "last_inquiry_at", "intent_at", "collected_at", "published_at")
    for field, value, source in candidates:
        for timestamp_key in timestamp_keys:
            timestamp = _recent_timestamp(source.get(timestamp_key), CURRENT_NEED_DAYS if field not in {"recent_inquiry", "inquiry", "inquired"} else RECENT_INQUIRY_DAYS)
            if timestamp:
                return {"qualified": True, "observed_at": timestamp, "evidence": value, "source_section": field, "reason": "Recent intent is explicitly researched and verified."}
    return {"qualified": False, "observed_at": None, "evidence": "", "source_section": None, "reason": "No recent intent is explicitly researched and verified."}


def _route_research(lead: Dict[str, Any], route: str) -> Dict[str, Any]:
    sections = _research_sections(lead)
    section = sections.get("route_research")
    if not section:
        return {"verified": False, "evidence": "", "reason": f"{route} route research is not explicitly verified."}
    routes = section.get("routes")
    route_item = routes.get(route) if isinstance(routes, dict) else section.get(route)
    if isinstance(route_item, dict):
        verified = _section_verified(route_item)
        evidence = str(route_item.get("evidence") or route_item.get("business_need") or route_item.get("need") or "").strip()
        return {"verified": verified and bool(evidence), "evidence": evidence, "reason": f"{route} route research verified." if verified and evidence else f"{route} route research is incomplete."}
    evidence = str(section.get("evidence") or section.get("business_need") or "").strip()
    return {"verified": True, "evidence": evidence, "reason": "Route research section verified."} if str(section.get("route") or "").strip() == route and _section_verified(section) and evidence else {"verified": False, "evidence": "", "reason": f"{route} route research is not explicitly verified."}


def _paxus_referral_checks(lead: Dict[str, Any], paxus_qualified: bool) -> Dict[str, Any]:
    research = lead.get("company_research") if isinstance(lead.get("company_research"), dict) else {}
    dm_verified = str(research.get("decision_maker_verification_status") or "").strip().lower() == "verified"
    company_verified = research.get("company_verified") is True
    named_contact = str(research.get("decision_maker") or "").strip()
    checks = {
        "paxus_base_qualification": {"passed": paxus_qualified, "reason": "Paxus base qualification passed." if paxus_qualified else "Paxus base qualification did not pass."},
        "company_verified": {"passed": company_verified, "reason": "Company research is explicitly verified." if company_verified else "Company research still requires verification."},
        "named_hiring_contact": {"passed": bool(named_contact and dm_verified), "reason": "Decision maker is explicitly verified." if named_contact and dm_verified else "Decision maker still requires research and verification."},
        "contact_communication": {"passed": lead.get("contact_communicated") is True, "reason": "Contact communication is recorded." if lead.get("contact_communicated") is True else "Contact communication has not been verified."},
        "contact_consent": {"passed": lead.get("contact_consent") is True, "reason": "Contact consent is recorded." if lead.get("contact_consent") is True else "Contact consent has not been verified."},
    }
    failures = [name for name, result in checks.items() if not result["passed"]]
    research_items = [name for name in ("company_verified", "named_hiring_contact") if not checks[name]["passed"]]
    verification_items = [name for name in ("contact_communication", "contact_consent") if not checks[name]["passed"]]
    return {"checks": checks, "passed": paxus_qualified and not failures, "failures": failures, "research_required": research_items, "verification_required": verification_items, "reason": "All Paxus referral gates passed." if paxus_qualified and not failures else "Paxus is not yet a true referral; missing or failed checks remain."}


def evaluate_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(lead, dict):
        raise ValueError("lead must be a dictionary")
    company_research = lead.get("company_research")
    if not isinstance(company_research, dict) or company_research.get("company_verified") is not True:
        return {"companies": {route: {"qualified": False, "category_score": 0, "matched_category": False, "current_need": {"qualified": False, "observed_at": None, "evidence": "", "reason": "Verified research required."}, "recent_inquiry": {"qualified": False, "observed_at": None, "evidence": "", "reason": "Verified research required."}, "route_research": {"verified": False, "evidence": "", "reason": "Verified company research required."}, "reason": "Verified company research is required before qualification."} for route in ROUTES}, "qualified_companies": [], "paxus_true_referral": False, "research_status": "research_required"}
    intent = _verified_intent(lead)
    general_text = _verified_research_text(lead)
    if not general_text:
        return {"companies": {route: {"qualified": False, "category_score": 0, "matched_category": False, "current_need": intent, "recent_inquiry": intent, "route_research": _route_research(lead, route), "reason": "No complete verified business-need research is available."} for route in ROUTES}, "qualified_companies": [], "paxus_true_referral": False, "research_status": "research_required"}
    results: Dict[str, Any] = {}
    for route in ROUTES:
        route_research = _route_research(lead, route)
        route_text = general_text
        if route_research["verified"] and route_research["evidence"]:
            route_text = f"{general_text} {route_research['evidence']}"
        category_scores = score_routes(company=str(lead.get("company") or ""), signal=route_text, evidence=route_text)
        category_score = int(category_scores.get(route, 0) or 0)
        if route == "Shiftr" and SHIFTR_SERVICE_NEED_CONTEXT.search(route_text):
            category_score = max(category_score, 1)
        qualified = category_score > 0 and intent["qualified"] and route_research["verified"]
        result = {"qualified": qualified, "category_score": category_score, "matched_category": category_score > 0, "current_need": intent, "recent_inquiry": intent, "route_research": route_research, "reason": "Verified research supports this route and recent intent." if qualified else "Route-specific verified research and recent intent are incomplete.", "qualification_timestamp": datetime.now(timezone.utc).isoformat()}
        if route == "Astrivon Labs":
            result["service_fit"] = list(match_astrivon_services(route_text))
            result["service_fit_verified"] = bool(result["service_fit"] and route_research["verified"])
        results[route] = result
    paxus = results["Paxus"]
    paxus_referral = _paxus_referral_checks(lead, paxus["qualified"])
    paxus["true_referral"] = paxus_referral["passed"]
    paxus["referral_status"] = "true_referral" if paxus_referral["passed"] else "research_required" if paxus["qualified"] else "not_ready"
    paxus["referral_checklist"] = paxus_referral
    qualified_routes = [route for route in ROUTES if results[route]["qualified"]]
    return {"companies": results, "qualified_companies": qualified_routes, "paxus_true_referral": paxus_referral["passed"], "research_status": "complete" if qualified_routes else "research_required"}


def _apply_primary_result(updated: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
    updated["qualification_results"] = evaluation["companies"]
    updated["research_status"] = evaluation["research_status"]
    updated["potential_routes"] = list(evaluation["qualified_companies"])
    updated["qualified"] = bool(evaluation["qualified_companies"])
    updated["qualification_review_stage"] = "primary"
    updated["qualification_primary_routes"] = list(evaluation["qualified_companies"])
    if updated["qualified"]:
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["qualification_status"] = "qualified"
        updated["review_state"] = "qualified"
        updated["reason_not_qualified"] = ""
    else:
        updated["status"] = IN_REVIEW
        updated["review_status"] = "Review"
        updated["qualification_status"] = "in_review"
        updated["review_state"] = "review"
        updated["reason_not_qualified"] = "Verified research is incomplete or no route currently satisfies all gates."
    return updated


def _independent_review(lead: Dict[str, Any]) -> Dict[str, Any]:
    prior = lead.get("qualification_results")
    if not isinstance(prior, dict):
        return {"qualified_companies": [], "disagreements": ["missing_primary_qualification_results"], "checked_routes": []}
    independent = []
    disagreements = []
    checked = []
    general_text = _verified_research_text(lead)
    for route in [str(item) for item in lead.get("potential_routes", []) if str(item).strip()]:
        checked.append(route)
        result = prior.get(route)
        if not isinstance(result, dict) or result.get("qualified") is not True:
            disagreements.append(f"{route}:primary_claim_not_qualified")
            continue
        route_research = result.get("route_research") if isinstance(result.get("route_research"), dict) else {}
        if route_research.get("verified") is not True:
            disagreements.append(f"{route}:route_research_not_verified")
            continue
        intent = result.get("current_need") if isinstance(result.get("current_need"), dict) else {}
        if not (intent.get("qualified") is True and intent.get("observed_at") and intent.get("evidence")):
            disagreements.append(f"{route}:intent_research_not_verified")
            continue
        route_text = f"{general_text} {route_research.get('evidence') or ''}".strip()
        independent_category_score = int(score_routes(company=str(lead.get("company") or ""), signal=route_text, evidence=route_text).get(route, 0) or 0)
        if route == "Shiftr" and SHIFTR_SERVICE_NEED_CONTEXT.search(route_text):
            independent_category_score = max(independent_category_score, 1)
        if independent_category_score <= 0:
            disagreements.append(f"{route}:category_evidence_failed")
            continue
        independent.append(route)
    return {"qualified_companies": independent, "disagreements": disagreements, "checked_routes": checked}


def _apply_independent_result(updated: Dict[str, Any]) -> Dict[str, Any]:
    review = _independent_review(updated)
    routes = review["qualified_companies"]
    updated["qualification_b_result"] = {"qualified_companies": list(routes), "disagreements": list(review["disagreements"]), "checked_routes": list(review["checked_routes"],), "independent": True, "reviewed_at": datetime.now(timezone.utc).isoformat()}
    updated["potential_routes"] = list(routes)
    updated["qualified"] = bool(routes)
    updated["qualification_review_stage"] = "validated"
    if routes:
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["qualification_status"] = "qualified"
        updated["review_state"] = "qualified"
        updated["reason_not_qualified"] = ""
    else:
        updated["status"] = IN_REVIEW
        updated["review_status"] = "Review"
        updated["qualification_status"] = "in_review"
        updated["review_state"] = "review"
        updated["reason_not_qualified"] = "Qualification B rejected all route claims."
    return updated


def apply_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(lead)
    if updated.get("qualification_review_stage") == "primary":
        return _apply_independent_result(updated)
    return _apply_primary_result(updated, evaluate_company_qualification(updated))


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
