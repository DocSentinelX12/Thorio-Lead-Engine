import pytest

from .lead_lifecycle import (
    can_transition,
    is_valid_status,
    normalize_status,
    transition_lead,
)


def test_normalize_status():
    assert normalize_status(
        "  QUALIFIED "
    ) == "qualified"


def test_valid_statuses():
    assert is_valid_status("new")
    assert is_valid_status("qualified")
    assert is_valid_status("approved")
    assert is_valid_status("delivered")
    assert is_valid_status("rejected")


def test_invalid_status():
    assert not is_valid_status("something_else")


def test_allowed_transitions():
    assert can_transition(
        "new",
        "qualified",
    )

    assert can_transition(
        "qualified",
        "approved",
    )

    assert can_transition(
        "approved",
        "delivered",
    )


def test_invalid_transition():
    assert not can_transition(
        "new",
        "delivered",
    )


def test_transition_lead():
    lead = {
        "company": "Acme",
        "status": "new",
    }

    result = transition_lead(
        lead,
        "qualified",
    )

    assert result["status"] == "qualified"
    assert result["company"] == "Acme"
    assert lead["status"] == "new"


def test_invalid_transition_raises():
    lead = {
        "company": "Acme",
        "status": "new",
    }

    with pytest.raises(ValueError):
        transition_lead(
            lead,
            "delivered",
        )
