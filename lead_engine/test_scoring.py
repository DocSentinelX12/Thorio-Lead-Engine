from .scoring import (
    priority_from_score,
    score_lead,
    score_result,
)


def test_strong_lead_gets_high_score():
    score = score_lead(
        "Acme",
        "remote software engineer",
        "Remote software engineer opening.",
    )

    assert score >= 8
    assert priority_from_score(score) == "High"


def test_medium_signal_gets_medium_priority():
    score = score_lead(
        "Example Corp",
        "remote role",
        "Company is hiring remotely.",
    )

    assert score >= 4
    assert priority_from_score(score) == "Medium"


def test_no_signal_returns_review():
    score = score_lead(
        "Unknown Corp",
        "general business news",
        "No relevant hiring information.",
    )

    assert score == 0
    assert priority_from_score(score) == "Review"


def test_score_result_returns_both_values():
    result = score_result(
        "Acme",
        "software engineer",
        "Engineering opening.",
    )

    assert "lead_score" in result
    assert "priority" in result
    assert result["lead_score"] > 0
