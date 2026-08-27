from typing import Dict


UNVERIFIED = "Unverified"
IN_REVIEW = "In Review"
QUALIFIED = "Qualified"
NOT_QUALIFIED = "Not Qualified"


VALID_STATUSES = {
    UNVERIFIED,
    IN_REVIEW,
    QUALIFIED,
    NOT_QUALIFIED,
}


def validate_status(status: str) -> bool:
    """
    Return True only when the qualification status is valid.
    """

    return status in VALID_STATUSES


def qualify_lead(
    lead: Dict[str, object],
    *,
    qualified: bool,
    reason: str = "",
) -> Dict[str, object]:
    """
    Apply a human qualification decision to a lead.

    This function requires an explicit caller decision.
    Scoring, routing, or evidence alone never qualifies a lead.
    """

    if not isinstance(qualified, bool):
        raise ValueError(
            "qualified must be explicitly True or False."
        )

    updated = dict(lead)

    if qualified:
        updated["qualified"] = True
        updated["status"] = QUALIFIED
        updated["review_status"] = "Qualified"
        updated["reason_not_qualified"] = ""

    else:
        updated["qualified"] = False
        updated["status"] = NOT_QUALIFIED
        updated["review_status"] = "Not Qualified"
        updated["reason_not_qualified"] = reason

    return updated


def begin_review(
    lead: Dict[str, object],
) -> Dict[str, object]:
    """
    Mark a lead as being reviewed by a human.
    """

    updated = dict(lead)

    updated["status"] = IN_REVIEW
    updated["review_status"] = "Review"

    return updated


if __name__ == "__main__":
    print(
        "Qualification module loaded. "
        "Human review is required before qualification."
    )
