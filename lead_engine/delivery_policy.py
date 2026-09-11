from typing import Any, Dict


SUPPORTED_ROUTES = ("Shiftr", "Paxus", "Thorio")
QUALIFIED_STATUSES = {"qualified", "approved", "accepted"}
MIN_DELIVERY_SCORE = 50


def _is_explicitly_qualified(lead: Dict[str, Any]) -> bool:
    """Require an explicit qualification decision before delivery."""
    if lead.get("qualified") is not True:
        return False
    return any(
        str(lead.get(key, "") or "").strip().lower() in QUALIFIED_STATUSES
        for key in ("qualification_status", "review_status", "status")
    )


def delivery_rejection_reason(lead: Dict[str, Any]) -> str:
    """Explain why a lead is not ready for partner delivery."""
    if not _is_explicitly_qualified(lead):
        return "lead_not_qualified"

    route = str(lead.get("route", "") or "").strip()
    if route not in SUPPORTED_ROUTES:
        return "unsupported_route"

    try:
        score = int(lead.get("lead_score", 0))
    except (TypeError, ValueError):
        score = 0
    if score < MIN_DELIVERY_SCORE:
        return "score_below_threshold"

    if not str(lead.get("company", "") or "").strip():
        return "missing_company"
    if not str(lead.get("person") or lead.get("contact_name") or "").strip():
        return "missing_contact"
    if not str(lead.get("business_need", "") or "").strip():
        return "missing_business_need"
    if not str(lead.get("signal", "") or "").strip():
        return "missing_signal"
    if not str(lead.get("evidence", "") or "").strip():
        return "missing_evidence"
    if not str(lead.get("url", "") or "").strip():
        return "missing_url"

    return ""


def is_delivery_ready(lead: Dict[str, Any]) -> bool:
    """Return True only for an explicitly qualified, complete opportunity."""
    return delivery_rejection_reason(lead) == ""
