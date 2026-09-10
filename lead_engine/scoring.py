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
}


ROUTE_SIGNAL_WEIGHTS = {
    "Shiftr": {
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
        "software development": 7,
        "development team": 7,
        "engineering team": 7,
        "development contractor": 8,
        "software contractor": 8,
        "technical talent": 6,
        "engineering talent": 6,
        "developer talent": 6,
        "staff augmentation": 8,
        "outsourcing": 7,
        "development team hiring": 8,
        "ai development": 7,
        "ai engineer": 7,
        "llm": 6,
        "llm integration": 8,
        "ai agent": 7,
        "ai agents": 7,
        "mobile development": 7,
        "mobile developer": 7,
        "mobile engineer": 7,
        "saas development": 7,
        "enterprise software development": 7,
    },
    "Paxus": {
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
        "recruiting engineers": 8,
        "staffing engineers": 8,
        "recruiting developers": 8,
        "staffing developers": 8,
        "technology recruiting": 9,
        "technical recruiting": 9,
        "engineering recruiting": 8,
        "technology hiring support": 8,
        "technical hiring support": 8,
        "engineering hiring support": 8,
        "recruitment support": 8,
        "staffing support": 8,
        "talent acquisition support": 8,
        "recruiting support": 8,
    },
    "Thorio": {
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
        "remote data": 7,
        "remote ai": 7,
        "remote machine learning": 8,
        "remote product": 7,
        "remote design": 7,
        "remote ux": 7,
        "remote ui": 7,
        "remote web": 7,
        "remote technical": 7,
    },
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
    Calculate the overall opportunity signal score.

    This preserves the broad signal pool. Qualification and routing remain
    separate decisions, and generic hiring language does not create a score.
    """
    text = _build_text(company=company, signal=signal, evidence=evidence)
    return sum(weight for phrase, weight in SIGNAL_WEIGHTS.items() if phrase in text)


def score_route(
    route: str,
    company: str,
    signal: str,
    evidence: str,
) -> int:
    """
    Calculate an independent route score.

    Route scoring intentionally uses only signals assigned to that route plus
    its route-specific bonuses. A strong signal for one partner therefore does
    not artificially inflate the score of another partner. Multi-route leads
    remain fully supported because each applicable route is scored separately.
    """
    text = _build_text(company=company, signal=signal, evidence=evidence)
    route_signals = ROUTE_SIGNAL_WEIGHTS.get(route, {})
    score = sum(weight for phrase, weight in route_signals.items() if phrase in text)
    bonuses = ROUTE_BONUSES.get(route, {})
    score += sum(weight for phrase, weight in bonuses.items() if phrase in text)
    return score


def priority_from_score(score: int) -> str:
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
    score = score_lead(company=company, signal=signal, evidence=evidence)
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
