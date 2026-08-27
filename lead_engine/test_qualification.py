import pytest

from .qualification import (
    IN_REVIEW,
    NOT_QUALIFIED,
    QUALIFIED,
    begin_review,
    qualify_lead,
    validate_status,
)


def test_new_lead_is_not_automatically_qualified():
    lead = {
        "company": "Acme",
        "lead_score": 8,
        "priority": "High",
        "qualified": False,
        "status": "Unverified",
    }

    assert lead["qualified"] is False
    assert lead["status"] == "Unverified"


def test_begin_review_changes_only_review_state():
    lead = {
        "company": "Acme",
        "qualified": False,
        "status": "Unverified",
    }

    result = begin_review(lead)

    assert result["status"] == IN_REVIEW
    assert result["review_status"] == "Review"
    assert result["qualified"] is False


def test_human_can_qualify_lead():
    lead = {
        "company": "Acme",
        "qualified": False,
        "status": "Unverified",
    }

    result = qualify_lead(
        lead,
        qualified=True,
    )

    assert result["qualified"] is True
    assert result["status"] == QUALIFIED
    assert result["review_status"] == "Qualified"
    assert result["reason_not_qualified"] == ""


def test_human_can_mark_lead_not_qualified():
    lead = {
        "company": "Acme",
        "qualified": False,
        "status": "In Review",
    }

    result = qualify_lead(
        lead,
        qualified=False,
        reason="No confirmed technology need.",
    )

    assert result["qualified"] is False
    assert result["status"] == NOT_QUALIFIED
    assert result["review_status"] == "Not Qualified"
    assert result["reason_not_qualified"] == (
        "No confirmed technology need."
    )


def test_qualification_requires_boolean_decision():
    lead = {
        "company": "Acme",
        "qualified": False,
        "status": "Unverified",
    }

    with pytest.raises(ValueError):
        qualify_lead(
            lead,
            qualified="yes",
        )


def test_status_validation():
    assert validate_status(QUALIFIED) is True
    assert validate_status(NOT_QUALIFIED) is True
    assert validate_status(IN_REVIEW) is True
    assert validate_status("something else") is False
