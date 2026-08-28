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


# These are specific technology job titles. They are strong enough
# to establish hiring intent when a source omits words such as
# "hiring", "opening", or "job".
#
# Generic company/technology terms are intentionally excluded.
# For example, "software company" must not become a Shiftr lead.
JOB_ROLE_CONTEXT = (
    r"\bsoftware engineer\b"
    r"|\bsoftware developer\b"
    r"\bsoftware development engineer\b"
    r"|\bfull[- ]stack engineer\b"
    r"|\bfull[- ]stack developer\b"
    r"|\bfrontend engineer\b"
    r"|\bfront[- ]end engineer\b"
    r"|\bfrontend developer\b"
    r"|\bfront[- ]end developer\b"
    r"|\bbackend engineer\b"
    r"|\bback[- ]end engineer\b"
    r"|\bbackend developer\b"
    r"|\bback[- ]end developer\b"
    r"|\bdata engineer\b"
    r"|\bdata scientist\b"
    r"|\bdata analyst\b"
    r"|\bmachine learning engineer\b"
    r"|\bml engineer\b"
    r"|\bai engineer\b"
    r"|\bai developer\b"
    r"|\bdevops engineer\b"
    r"|\bcloud engineer\b"
    r"|\bplatform engineer\b"
    r"|\bsite reliability engineer\b"
    r"|\bsre\b"
    r"|\bproduct manager\b"
    r"|\bproduct designer\b"
    r"|\bux designer\b"
    r"|\bui designer\b"
    r"|\btechnical designer\b"
    r"|\btechnology professional\b"
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


def _text(
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


def _has_hiring_context(
    text: str,
) -> bool:
    return bool(
        re.search(
            HIRING_CONTEXT,
            text,
            re.IGNORECASE,
        )
    )


def _has_job_role_context(
    text: str,
) -> bool:
    return bool(
        re.search(
            JOB_ROLE_CONTEXT,
            text,
            re.IGNORECASE,
        )
    )


def _matches(
    text: str,
    patterns: List[str],
) -> int:
    return sum(
        bool(
            re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )
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

    Explicit hiring language or a specific technology job title
    establishes enough context to evaluate the route. Generic
    company descriptions do not.
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

    if not (
        _has_hiring_context(text)
        or _has_job_role_context(text)
    ):
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
