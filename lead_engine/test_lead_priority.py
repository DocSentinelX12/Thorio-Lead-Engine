from .lead_priority import (
    assign_priority,
    priority_for_score,
)


def test_critical_priority():
    assert priority_for_score(90) == "Critical"
    assert priority_for_score(100) == "Critical"


def test_high_priority():
    assert priority_for_score(75) == "High"
    assert priority_for_score(89) == "High"


def test_medium_priority():
    assert priority_for_score(50) == "Medium"
    assert priority_for_score(74) == "Medium"


def test_low_priority():
    assert priority_for_score(0) == "Low"
    assert priority_for_score(49) == "Low"


def test_invalid_score_is_low():
    assert priority_for_score("invalid") == "Low"
    assert priority_for_score(None) == "Low"


def test_assign_priority():
    lead = {
        "company": "Acme",
        "lead_score": 85,
    }

    result = assign_priority(lead)

    assert result["company"] == "Acme"
    assert result["lead_score"] == 85
    assert result["priority"] == "High"


def test_assign_priority_does_not_mutate():
    lead = {
        "company": "Acme",
        "lead_score": 95,
    }

    result = assign_priority(lead)

    assert "priority" not in lead
    assert result["priority"] == "Critical"
    assert result is not lead


def test_assign_priority_missing_score():
    result = assign_priority(
        {"company": "Acme"}
    )

    assert result["priority"] == "Low"
