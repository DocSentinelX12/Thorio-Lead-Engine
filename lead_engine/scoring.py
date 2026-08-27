from typing import Dict


SIGNAL_WEIGHTS = {
    "software engineer": 3,
    "developer": 3,
    "engineering hire": 3,
    "contract developer": 3,
    "technology recruitment": 3,
    "it recruitment": 3,
    "tech recruitment": 3,
    "technology staffing": 3,
    "remote": 2,
    "remote-first": 2,
    "remote hiring": 2,
    "remote role": 2,
}


def score_lead(
    company: str,
    signal: str,
    evidence: str,
) -> int:
    """
    Calculate an opportunity signal score.

    This is a prioritization score only.
    It does not qualify or reject a lead.
    """

    text = (
        f"{company} {signal} {evidence}"
    ).lower()

    score = 0

    for phrase, weight in SIGNAL_WEIGHTS.items():
        if phrase in text:
            score += weight

    return score


def priority_from_score(score: int) -> str:
    """
    Convert a numeric signal score into a review priority.
    """

    if score >= 8:
        return "High"

    if score >= 4:
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
    Return both the score and review priority.
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


if __name__ == "__main__":
    print(
        score_result(
            "Acme",
            "remote software engineer",
            "Remote engineering opening.",
        )
    )
