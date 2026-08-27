from typing import Any, Dict, List
import re


PARTNER_ROUTES = {
    "Shiftr": {
        "required_signal_terms": (
            "software",
            "engineer",
            "developer",
            "development",
            "technology",
            "tech",
            "engineering",
            "cto",
            "technical",
            "it",
        ),
    },
    "Paxus": {
        "required_signal_terms": (
            "staffing",
            "contract",
            "contractor",
            "workforce",
            "recruiting",
            "recruitment",
            "talent",
            "hiring",
            "consultant",
            "consulting",
        ),
    },
    "Thorio": {
        "required_signal_terms": (
            "remote",
            "software",
            "engineer",
            "developer",
            "development",
            "technology",
            "tech",
            "engineering",
            "data",
            "product",
            "designer",
            "design",
            "ai",
            "machine learning",
            "ml",
        ),
    },
}


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _term_matches_text(term: str, text: str) -> bool:
    """
    Match a route term as a whole word or phrase.

    This prevents short terms such as 'it', 'ai', and 'ml'
    from matching inside unrelated words or company names.
    """

    term = normalize_text(term)

    if not term:
        return False

    pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"

    return re.search(pattern, text) is not None


def route_matches_partner(
    route: str,
    signal: str = "",
    evidence: str = "",
    company: str = "",
) -> bool:
    """
    Determine whether the lead's evidence supports its assigned partner route.

    Route terms are matched as complete words or phrases rather than
    arbitrary substrings. Generic words must therefore not create a
    false-positive route merely because they occur inside another word.
    """

    route = str(route or "").strip()

    if route not in PARTNER_ROUTES:
        return False

    text = normalize_text(
        " ".join(
            [
                str(signal or ""),
                str(evidence or ""),
                str(company or ""),
            ]
        )
    )

    terms = PARTNER_ROUTES[route]["required_signal_terms"]

    return any(
        _term_matches_text(term, text)
        for term in terms
    )


def validate_partner_route(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a structured validation result for a lead's assigned route.
    """

    route = str(lead.get("route", "")).strip()

    if route not in PARTNER_ROUTES:
        return {
            "valid": False,
            "route": route,
            "reason": "unsupported_route",
        }

    if not route_matches_partner(
        route=route,
        signal=lead.get("signal", ""),
        evidence=lead.get("evidence", ""),
        company=lead.get("company", ""),
    ):
        return {
            "valid": False,
            "route": route,
            "reason": "route_evidence_mismatch",
        }

    return {
        "valid": True,
        "route": route,
        "reason": "",
    }


def supported_partner_routes() -> List[str]:
    return list(PARTNER_ROUTES.keys())
