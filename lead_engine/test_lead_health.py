from .lead_health import health_summary


def test_health_summary():
    leads = [
        {
            "company": "A",
            "lead_score": 90,
            "contact_email": "a@example.com",
        },
        {
            "company": "B",
            "lead_score": 70,
            "contact_email": "",
        },
        {
            "company": "C",
            "contact_email": "c@example.com",
        },
    ]

    result = health_summary(leads)

    assert result["total"] == 3
    assert result["scored"] == 2
    assert result["unscored"] == 1
    assert result["with_contact"] == 2
    assert result["without_contact"] == 1


def test_health_score_coverage():
    leads = [
        {"lead_score": 90},
        {"lead_score": 80},
        {},
        {},
    ]

    result = health_summary(leads)

    assert result["score_coverage"] == 0.5


def test_health_contact_coverage():
    leads = [
        {"contact_email": "a@example.com"},
        {"contact_email": "b@example.com"},
        {"contact_email": ""},
        {},
    ]

    result = health_summary(leads)

    assert result["contact_coverage"] == 0.5


def test_health_ignores_invalid_scores():
    leads = [
        {"lead_score": "invalid"},
        {"lead_score": 80},
    ]

    result = health_summary(leads)

    assert result["scored"] == 1
    assert result["unscored"] == 1


def test_health_strips_email():
    leads = [
        {"contact_email": "  a@example.com  "},
    ]

    result = health_summary(leads)

    assert result["with_contact"] == 1


def test_health_empty():
    assert health_summary([]) == {
        "total": 0,
        "scored": 0,
        "unscored": 0,
        "with_contact": 0,
        "without_contact": 0,
        "score_coverage": 0.0,
        "contact_coverage": 0.0,
    }


def test_health_accepts_generator():
    leads = (
        {"lead_score": 90}
        for _ in range(3)
    )

    result = health_summary(leads)

    assert result["total"] == 3
    assert result["scored"] == 3
