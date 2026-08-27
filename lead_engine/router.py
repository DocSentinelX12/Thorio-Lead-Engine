import re
from typing import Dict, List


RULES = {
    "Shiftr": [
        r"\bindividual developer\b",
        r"\bsoftware engineer\b",
        r"\bdeveloper\b",
        r"\bcontract developer\b",
        r"\bengineering hire\b",
    ],
    "Paxus": [
        r"\btechnology recruitment\b",
        r"\bit recruitment\b",
        r"\btech recruitment\b",
        r"\btechnology staffing\b",
    ],
    "Thorio": [
        r"\bremote\b",
        r"\bremote-first\b",
        r"\bremote hiring\b",
        r"\bremote role\b",
    ],
}


def score_routes(
    company: str,
    signal: str,
    evidence: str,
) -> Dict[str, int]:
    """
    Score every potential business opportunity.

    A lead can match multiple businesses.
    No qualification decision is made here.
    """

    text = f"{company} {signal} {evidence}".lower()

    return {
        name: sum(
            bool(re.search(pattern, text))
            for pattern in patterns
        )
        for name, patterns in RULES.items()
    }


def route(
    company: str,
    signal: str,
    evidence: str,
) -> str:
    """
    Return the strongest single route for compatibility
    with the existing Lead.route field.
    """

    scores = score_routes(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    best = max(scores, key=scores.get)

    if scores[best] == 0:
        return "Review"

    return best


def potential_routes(
    company: str,
    signal: str,
    evidence: str,
) -> List[str]:
    """
    Return every business with at least one matching signal.

    This preserves multi-opportunity leads instead of discarding
    secondary matches.
    """

    scores = score_routes(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    return [
        name
        for name, score in scores.items()
        if score > 0
    ]


if __name__ == "__main__":
    print(
        potential_routes(
            "Acme",
            "remote software engineer",
            "Company is hiring a remote software engineer.",
        )
    )
