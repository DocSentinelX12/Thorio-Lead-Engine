from typing import Any, Dict


SUPPORTED_ROUTES = ("Shiftr", "Paxus", "Thorio")

MIN_DELIVERY_SCORE = 50


def is_delivery_ready(lead: Dict[str, Any]) -> bool:
    """
    Return True only when a lead has enough information and quality
    to enter partner delivery.
    """

    route = str(lead.get("route", "")).strip()

    if route not in SUPPORTED_ROUTES:
        return False

    try:
        score = int(lead.get("lead_score", 0))
    except (TypeError, ValueError):
        score = 0

    if score < MIN_DELIVERY_SCORE:
        return False

    company = str(lead.get("company", "")).strip()
    signal = str(lead.get("signal", "")).strip()
    evidence = str(lead.get("evidence", "")).strip()
    url = str(lead.get("url", "")).strip()

    if not company:
        return False

    if not signal:
        return False

    if not evidence:
        return False

    if not url:
        return False

    return True


def delivery_rejection_reason(lead: Dict[str, Any]) -> str:
    """
    Explain why a lead is not ready for partner delivery.
    Returns an empty string when the lead is ready.
    """

    route = str(lead.get("route", "")).strip()

    if route not in SUPPORTED_ROUTES:
        return "unsupported_route"

    try:
        score = int(lead.get("lead_score", 0))
    except (TypeError, ValueError):
        score = 0

    if score < MIN_DELIVERY_SCORE:
        return "score_below_threshold"

    if not str(lead.get("company", "")).strip():
        return "missing_company"

    if not str(lead.get("signal", "")).strip():
        return "missing_signal"

    if not str(lead.get("evidence", "")).strip():
        return "missing_evidence"

    if not str(lead.get("url", "")).strip():
        return "missing_url"

    return ""
