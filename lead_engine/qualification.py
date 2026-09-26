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
CURRENT_NEED_CONTEXT = re.compile(r"\b(?:hiring|hire|hiring for|recruiting|recruit|opening|open role|looking to hire|seeking|staffing|recruitment support|technology recruitment|development contractor|staff augmentation|outsourcing|outsource|llm integration|ai agents?|saas development|mobile development|software development|engineering team|development team|dev agency|tech partner|mvp|b2b outreach|b2b sales|lead generation|sales automation|computer vision|business workflow|crm automation|automate business workflow|seed funding|non-technical founder|web/mobile app|product development|software development)\b", re.I)
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
    sections = _research_sections(lead)
    verified_parts: list[str] = []
    for key, section in sections.items():
        if not _section_verified(section):
            continue
        for field in ("business_need", "current_need", "recent_inquiry", "need", "service_need", "requirement", "role", "description", "intent"):
            value = section.get(field)
            if isinstance(value, str) and value.strip():
                verified_parts.append(value.strip())
        if key == "route_research":
            routes = section.get("routes")
            if isinstance(routes, dict) and route:
                route_item = routes.get(route)
                if isinstance(route_item, dict) and _section_verified(route_item):
                    for field in ("evidence", "business_need", "current_need", "need", "service_need", "requirement", "description"):
                        value = route_item.get(field)
                        if isinstance(value, str) and value.strip():
                            verified_parts.append(value.strip())
    return " ".join(verified_parts)


def _verified_intent(lead: Dict[str, Any]) -> Dict[str, Any]:
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
    for field, value, section in candidates:
        timestamp = None
        for key in ("observed_at", "need_at", "current_need_at", "hiring_need_at", "inquiry_at", "inquired_at", "last_inquiry_at", "intent_at"):
            timestamp = _recent_timestamp(section.get(key), CURRENT_NEED_DAYS)
            if timestamp:
                break
        if timestamp:
            return {"qualified": True, "observed_at": timestamp, "evidence": value, "source_section": field, "reason": "Recent intent is explicitly researched and verified."}
    return {"qualified": False, "observed_at": None, "evidence": "", "source_section": None, "reason": "No recent intent is explicitly researched and verified."}


def _route_research(lead: Dict[str, Any], route: str) -> Dict[str, Any]:
    sections = _research_sections(lead)
    section = sections.get("route_research")
    if not section or not _section_verified(section):
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
        service_fit = list(match_astrivon_services(route_text)) if route == "Astrivon Labs" else []
        if route == "Astrivon Labs" and service_fit:
            category_score = max(category_score, 1)
        qualified = category_score > 0 and intent["qualified"] and route_research["verified"]
        results[route] = {"qualified": qualified, "category_score": category_score, "matched_category": category_score > 0, "current_need": intent, "recent_inquiry": intent, "route_research": route_research, "service_fit": service_fit, "service_fit_verified": bool(service_fit and route_research["verified"]), "reason": "Verified research supports this route and recent intent." if qualified else "Route-specific verified research and recent intent are incomplete.", "qualification_timestamp": datetime.now(timezone.utc).isoformat()}
    paxus = results["Paxus"]
    paxus_referral = _paxus_referral_checks(lead, paxus["qualified"])
    paxus["true_referral"] = paxus_referral["passed"]
    paxus["referral_status"] = "true_referral" if paxus_referral["passed"] else "research_required" if paxus["qualified"] else "not_ready"
    paxus["referral_checklist"] = paxus_referral
    qualified_routes = [route for route in ROUTES if results[route]["qualified"]]
    return {"companies": results, "qualified_companies": qualified_routes, "paxus_true_referral": paxus_referral["passed"], "research_status": "complete" if qualified_routes else "research_required"}


def apply_company_qualification(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the canonical qualification result without collapsing independent routes.

    This adapter is the stable contract consumed by the discovery gate and agent workers.
    It preserves the complete lead payload and derives lifecycle fields only from the
    evidence-backed evaluator above. A partner route may qualify independently of every
    other route; missing downstream verification must never erase a valid qualification.
    """
    if not isinstance(lead, dict):
        raise ValueError("lead must be a dictionary")
    evaluated = evaluate_company_qualification(dict(lead))
    companies = evaluated.get("companies") if isinstance(evaluated.get("companies"), dict) else {}
    potential_routes = [route for route in ROUTES if isinstance(companies.get(route), dict) and companies[route].get("qualified") is True]
    result = dict(lead)
    result["qualification_results"] = companies
    result["potential_routes"] = potential_routes
    result["qualified_companies"] = list(potential_routes)
    result["qualified"] = bool(potential_routes)
    result["route"] = potential_routes[0] if len(potential_routes) == 1 else ("Review" if not potential_routes else "Multi-route")
    result["research_status"] = evaluated.get("research_status", result.get("research_status", "research_required"))
    result["qualification_status"] = QUALIFIED if result["qualified"] else NOT_QUALIFIED
    result["qualification_review_stage"] = "validated"
    result["qualification_timestamp"] = datetime.now(timezone.utc).isoformat()
    result["paxus_true_referral"] = bool(evaluated.get("paxus_true_referral"))
    if "Paxus" in companies:
        result["paxus_referral_status"] = companies["Paxus"].get("referral_status", "not_ready")
        result["paxus_referral_checklist"] = companies["Paxus"].get("referral_checklist", {})
    astrivon = companies.get("Astrivon Labs")
    if isinstance(astrivon, dict):
        result["astrivon_service_fit"] = list(astrivon.get("service_fit") or [])
        result["astrivon_service_fit_verified"] = bool(astrivon.get("service_fit_verified"))
    return result
