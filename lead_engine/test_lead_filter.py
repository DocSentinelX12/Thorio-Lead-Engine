from .lead_filter import (
    filter_by_min_score,
    filter_by_route,
    filter_by_status,
)


def test_filter_by_min_score():
    leads = [
        {"company": "A", "lead_score": 90},
        {"company": "B", "lead_score": 70},
        {"company": "C", "lead_score": 50},
    ]

    result = filter_by_min_score(leads, 70)

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "B"]


def test_filter_by_min_score_includes_exact_match():
    lead = {
        "company": "A",
        "lead_score": 75,
    }

    assert filter_by_min_score([lead], 75) == [lead]


def test_filter_by_min_score_ignores_invalid_scores():
    leads = [
        {"company": "A", "lead_score": "invalid"},
        {"company": "B", "lead_score": 80},
    ]

    result = filter_by_min_score(leads, 70)

    assert [
        lead["company"]
        for lead in result
    ] == ["B"]


def test_filter_by_route_is_case_insensitive():
    leads = [
        {"company": "A", "route": "Shiftr"},
        {"company": "B", "route": "Paxus"},
    ]

    result = filter_by_route(leads, "shiftr")

    assert result == [leads[0]]


def test_filter_by_route_strips_whitespace():
    lead = {
        "company": "A",
        "route": " Shiftr ",
    }

    assert filter_by_route([lead], "Shiftr") == [lead]


def test_filter_by_status():
    leads = [
        {"company": "A", "status": "new"},
        {"company": "B", "status": "qualified"},
        {"company": "C", "status": "new"},
    ]

    result = filter_by_status(leads, "new")

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C"]


def test_filters_return_copies():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "status": "new",
        "lead_score": 90,
    }

    result = filter_by_min_score([lead], 80)

    assert result[0] == lead
    assert result[0] is not lead


def test_empty_filters():
    assert filter_by_min_score([], 50) == []
    assert filter_by_route([], "Shiftr") == []
    assert filter_by_status([], "new") == []
