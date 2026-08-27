from .lead_metrics import lead_metrics


def test_lead_metrics_total():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
    ]

    result = lead_metrics(leads)

    assert result["total"] == 3


def test_lead_metrics_average_score():
    leads = [
        {"lead_score": 80},
        {"lead_score": 60},
        {"lead_score": 100},
    ]

    result = lead_metrics(leads)

    assert result["scored"] == 3
    assert result["average_score"] == 80.0


def test_lead_metrics_high_priority():
    leads = [
        {"priority": "High"},
        {"priority": "Medium"},
        {"priority": "high"},
        {"priority": "Low"},
    ]

    result = lead_metrics(leads)

    assert result["high_priority"] == 2


def test_lead_metrics_handles_invalid_scores():
    leads = [
        {"lead_score": 100},
        {"lead_score": "invalid"},
        {"lead_score": None},
    ]

    result = lead_metrics(leads)

    assert result["scored"] == 2
    assert result["average_score"] == 50.0


def test_lead_metrics_no_scores():
    leads = [
        {"company": "A"},
        {"company": "B"},
    ]

    result = lead_metrics(leads)

    assert result["total"] == 2
    assert result["scored"] == 0
    assert result["average_score"] == 0.0


def test_lead_metrics_empty():
    result = lead_metrics([])

    assert result == {
        "total": 0,
        "scored": 0,
        "average_score": 0.0,
        "high_priority": 0,
    }


def test_lead_metrics_accepts_generators():
    leads = (
        {"lead_score": 90}
        for _ in range(3)
    )

    result = lead_metrics(leads)

    assert result["total"] == 3
    assert result["scored"] == 3
    assert result["average_score"] == 90.0
