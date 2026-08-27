import re


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


def route(company: str, signal: str, evidence: str) -> str:
    text = f"{company} {signal} {evidence}".lower()

    scores = {
        name: sum(
            bool(re.search(pattern, text))
            for pattern in patterns
        )
        for name, patterns in RULES.items()
    }

    best = max(scores, key=scores.get)

    if scores[best] == 0:
        return "Review"

    return best
