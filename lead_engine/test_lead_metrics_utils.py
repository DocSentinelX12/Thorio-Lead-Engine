from .lead_metrics_utils import (
    average_score,
    highest_score,
    lowest_score,
)


def test_average_score():
    leads = [
        {"lead_score": 80},
        {"lead_score": 60},
        {"lead_score": 100},
    ]

    assert average_score(leads) == 80.0


def test_average_score_handles_strings():
    leads = [
        {"lead_score": "80"},
        {"lead_score": "60"},
    ]

    assert average_score(leads) == 70.0


def test_average_score_ignores_invalid_values():
    leads = [
        {"lead_score": 80},
        {"lead_score": "invalid"},
        {"lead_score": 60},
    ]

    assert average_score(leads) == 70.0


def test_average_score_empty():
    assert average_score([]) == 0.0


def test_highest_score():
    leads = [
        {"lead_score": 40},
        {"lead_score": 95},
        {"lead_score": 70},
    ]

    assert highest_score(leads) == 95.0


def test_highest_score_empty():
    assert highest_score([]) == 0.0


def test_lowest_score():
    leads = [
        {"lead_score": 40},
        {"lead_score": 95},
        {"lead_score": 70},
    ]

    assert lowest_score(leads) == 40.0


def test_lowest_score_empty():
    assert lowest_score([]) == 0.0
