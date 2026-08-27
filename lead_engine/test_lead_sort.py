from .lead_sort import (
    sort_by_priority,
    sort_by_score,
)


def test_sort_by_score_descending():
    leads = [
        {"company": "A", "lead_score": 50},
        {"company": "B", "lead_score": 90},
        {"company": "C", "lead_score": 70},
    ]

    result = sort_by_score(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "C", "A"]


def test_sort_by_score_ascending():
    leads = [
        {"company": "A", "lead_score": 50},
        {"company": "B", "lead_score": 90},
        {"company": "C", "lead_score": 70},
    ]

    result = sort_by_score(
        leads,
        descending=False,
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C", "B"]


def test_sort_by_score_handles_strings():
    leads = [
        {"company": "A", "lead_score": "40"},
        {"company": "B", "lead_score": "80"},
    ]

    result = sort_by_score(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "A"]


def test_sort_by_score_handles_invalid_values():
    leads = [
        {"company": "A", "lead_score": "invalid"},
        {"company": "B", "lead_score": 50},
    ]

    result = sort_by_score(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "A"]


def test_sort_by_priority():
    leads = [
        {"company": "A", "priority": "Low"},
        {"company": "B", "priority": "Critical"},
        {"company": "C", "priority": "High"},
        {"company": "D", "priority": "Medium"},
    ]

    result = sort_by_priority(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "C", "D", "A"]


def test_sort_by_priority_ascending():
    leads = [
        {"company": "A", "priority": "Low"},
        {"company": "B", "priority": "Critical"},
        {"company": "C", "priority": "High"},
    ]

    result = sort_by_priority(
        leads,
        descending=False,
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C", "B"]


def test_sort_returns_copies():
    lead = {
        "company": "Acme",
        "lead_score": 90,
    }

    result = sort_by_score([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_sort_empty():
    assert sort_by_score([]) == []
    assert sort_by_priority([]) == []
