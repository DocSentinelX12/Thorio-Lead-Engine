import re
from typing import Dict, List


ROUTES = ("Shiftr", "Paxus", "Thorio")


HIRING_CONTEXT = (
    r"\bhir(?:e|ing|ed)\b"
    r"|\brecruit(?:ment|ing|ed)?\b"
    r"|\bstaff(?:ing|ed)?\b"
    r"|\bopening\b"
    r"|\bposition\b"
    r"|\brole\b"
    r"|\bvacanc(?:y|ies)\b"
    r"|\bjob\b"
)


SHIFTR_RULES = [
    r"\bindividual developer\b",
    r"\bsoftware engineer\b",
    r"\bsoftware developer\b",
    r"\bdeveloper\b",
    r"\bengineering hire\b",
    r"\bengineering hiring\b",
    r"\bcontract developer\b",
    r"\bcontract engineer\b",
    r"\bfreelance developer\b",
    r"\bindividual engineer\b",
    r"\bdeveloper contractor\b",
    r"\bsoftware development contractor\b",
    r"\btechnical contractor\b",
    r"\bengineering contractor\b",
    r"\bdevelopment team hiring\b",
]


PAXUS_RULES = [
    r"\btechnology recruitment\b",
    r"\btech recruitment\b",
    r"\bit recruitment\b",
    r"\btechnical recruitment\b",
    r"\btechnology staffing\b",
    r"\bit staffing\b",
    r"\btechnical staffing\b",
    r"\bengineering recruitment\b",
    r"\bengineering staffing\b",
    r"\btechnology talent acquisition\b",
    r"\bit talent acquisition\b",
    r"\brecruiting technology professionals\b",
    r"\bstaffing technology professionals\b",
]


THORIO_REMOTE_RULES = [
    r"\bremote software engineer\b",
    r"\bremote software developer\b",
    r"\bremote developer\b",
    r"\bremote engineer\b",
    r"\bremote engineering\b",
    r"\bremote product designer\b",
    r"\bremote designer\b",
    r"\bremote product manager\b",
    r"\bremote product role\b",
    r"\bremote data scientist\b",
    r"\bremote data analyst\b",
    r"\bremote data engineer\b",
    r"\bremote machine learning\b",
    r"\bremote ml engineer\b",
    r"\bremote ai engineer\b",
    r"\bremote technology role\b",
    r"\bremote tech role\b",
    r"\bremote technical role\b",
    r"\bremote-first hiring\b",
    r"\bremote hiring\b",
    r"\bwork-from-home technology role\b",
    r"\bdistributed engineering\b",
    r"\bdistributed development\b",
    r"\bremote engineering position\b",
    r"\bremote engineering role\b",
]


def _text(company: str, signal: str, evidence: str) -> str:
    return " ".join(
        [
            company or "",
            signal or "",
            evidence or "",
        ]
    ).lower()


def _has_hiring_context(text: str) -> bool:
    return bool(
        re.search(
            HIRING_CONTEXT,
            text,
            re.IGNORECASE,
        )
    )


def _matches(text: str, patterns: List[str]) -> int:
    return sum(
        bool(re.search(pattern, text, re.IGNORECASE))
        for pattern in patterns
    )


def score_routes(
    company: str,
    signal: str,
    evidence: str,
) -> Dict[str, int]:
    """
    Score an opportunity for each business route.

    Routing identifies business relevance only.
    Qualification is handled elsewhere in the pipeline.

    A lead may be relevant to more than one destination.
    """

    text = _text(
        company,
        signal,
        evidence,
    )

    scores = {
        "Shiftr": 0,
        "Paxus": 0,
        "Thorio": 0,
    }

    if not _has_hiring_context(text):
        return scores

    scores["Shiftr"] = _matches(
        text,
        SHIFTR_RULES,
    )

    scores["Paxus"] = _matches(
        text,
        PAXUS_RULES,
    )

    scores["Thorio"] = _matches(
        text,
        THORIO_REMOTE_RULES,
    )

    return scores


def route(
    company: str,
    signal: str,
    evidence: str,
) -> str:
    """
    Return the primary business route.

    Direct software/developer/engineering hiring defaults
    to Shiftr.

    Technology recruitment and staffing defaults to Paxus.

    Remote technology hiring defaults to Thorio when no
    stronger Shiftr or Paxus signal exists.
    """

    scores = score_routes(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    if scores["Shiftr"] > 0:
        return "Shiftr"

    if scores["Paxus"] > 0:
        return "Paxus"

    if scores["Thorio"] > 0:
        return "Thorio"

    return "Review"


def potential_routes(
    company: str,
    signal: str,
    evidence: str,
) -> List[str]:
    """
    Return every business route with a positive score.
    """

    scores = score_routes(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    return [
        name
        for name in ROUTES
        if scores[name] > 0
    ]


if __name__ == "__main__":
    print(
        potential_routes(
            "Acme",
            "remote software engineer",
            "Company is hiring a remote software engineer.",
        )
    )
