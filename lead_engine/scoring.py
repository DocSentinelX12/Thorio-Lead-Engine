from typing import Dict


SIGNAL_WEIGHTS = {
    # Shiftr-oriented signals
    "individual developer": 8,
    "software engineer": 7,
    "software developer": 7,
    "developer": 6,
    "engineering hire": 7,
    "engineering hiring": 7,
    "contract developer": 8,
    "contract engineer": 8,
    "freelance developer": 7,
    "developer contractor": 8,
    "technical contractor": 7,
    "engineering contractor": 7,

    # Paxus-oriented signals
    "technology recruitment": 9,
    "tech recruitment": 9,
    "it recruitment": 9,
    "technical recruitment": 9,
    "technology staffing": 9,
    "it staffing": 9,
    "technical staffing": 9,
    "engineering recruitment": 8,
    "engineering staffing": 8,
    "technology talent acquisition": 8,
    "it talent acquisition": 8,

    # Thorio-oriented signals
    "remote software engineer": 8,
    "remote software developer": 8,
    "remote developer": 8,
    "remote engineer": 7,
    "remote engineering": 7,
    "remote product designer": 8,
    "remote designer": 7,
    "remote product manager": 8,
    "remote data scientist": 8,
    "remote data analyst": 8,
    "remote data engineer": 8,
    "remote machine learning": 8,
    "remote ml engineer": 8,
    "remote ai engineer": 8,
    "remote technology role": 8,
    "remote tech role": 8,
    "remote technical role": 8,
    "remote-first hiring": 7,
    "remote hiring": 6,
    "work-from-home technology role": 8,
    "distributed engineering": 7,
    "distributed development": 7,
    "remote engineering position": 8,
    "remote engineering role": 8,

    # General buying-intent signals
    "hiring": 2,
    "opening": 2,
    "position": 1,
    "role": 1,
    "job": 1,
}


ROUTE_BONUSES = {
    "Shiftr": {
        "developer": 3,
        "engineer": 3,
        "contract": 3,
        "freelance": 3,
    },
    "Paxus": {
        "recruitment": 4,
        "staffing": 4,
        "talent acquisition": 3,
    },
    "Thorio": {
        "remote": 4,
        "distributed": 3,
        "work-from-home": 4,
        "remote-first": 4,
    },
}


def _build_text(
    company: str,
    signal: str,
    evidence: str,
) -> str:
    return " ".join(
        [
            company or "",
            signal or "",
            evidence or "",
        ]
    ).lower()


def score_lead(
    company: str,
    signal: str,
    evidence: str,
) -> int:
    """
    Calculate a lead-intent score.

    This score measures the strength of the observable
    opportunity signal only.

    It does not qualify or reject a lead.
    """

    text = _build_text(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    score = 0

    for phrase, weight in SIGNAL_WEIGHTS.items():
        if phrase in text:
            score += weight

    return score


def score_route(
    route: str,
    company: str,
    signal: str,
    evidence: str,
) -> int:
    """
    Calculate a route-specific opportunity score.

    This allows the same lead to be evaluated differently
    for Shiftr, Paxus, and Thorio.
    """

    text = _build_text(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    score = score_lead(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    bonuses = ROUTE_BONUSES.get(
        route,
        {},
    )

    for phrase, weight in bonuses.items():
        if phrase in text:
            score += weight

    return score


def priority_from_score(score: int) -> str:
    """
    Convert a numeric opportunity score into a review priority.
    """

    if score >= 20:
        return "Critical"

    if score >= 12:
        return "High"

    if score >= 6:
        return "Medium"

    if score > 0:
        return "Low"

    return "Review"


def score_result(
    company: str,
    signal: str,
    evidence: str,
) -> Dict[str, object]:
    """
    Return the overall score and review priority.

    Qualification remains a separate human decision.
    """

    score = score_lead(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    return {
        "lead_score": score,
        "priority": priority_from_score(score),
    }


def route_score_result(
    route: str,
    company: str,
    signal: str,
    evidence: str,
) -> Dict[str, object]:
    """
    Return a route-specific score and priority.
    """

    score = score_route(
        route=route,
        company=company,
        signal=signal,
        evidence=evidence,
    )

    return {
        "route": route,
        "route_score": score,
        "priority": priority_from_score(score),
    }


if __name__ == "__main__":
    print(
        score_result(
            company="Acme",
            signal="remote software engineer",
            evidence="Acme is hiring a remote software engineer.",
        )
    )
