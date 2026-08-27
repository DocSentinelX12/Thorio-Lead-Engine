from .lead_dedupe import (
    deduplicate_leads,
    duplicate_count,
)


def test_deduplicate_leads_removes_duplicates():
    leads = [
        {
            "source": "linkedin",
            "source_id": "1",
            "company": "Acme",
        },
        {
            "source": "linkedin",
            "source_id": "1",
            "company": "Acme",
        },
        {
            "source": "linkedin",
            "source_id": "2",
            "company": "Beta",
        },
    ]

    result = deduplicate_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["Acme", "Beta"]


def test_deduplicate_preserves_first_record():
    first = {
        "source": "test",
        "source_id": "123",
        "company": "Acme",
        "lead_score": 50,
    }

    second = {
        "source": "test",
        "source_id": "123",
        "company": "Acme",
        "lead_score": 100,
    }

    result = deduplicate_leads([first, second])

    assert result == [first]


def test_deduplicate_preserves_order():
    leads = [
        {"source": "test", "source_id": "1"},
        {"source": "test", "source_id": "2"},
        {"source": "test", "source_id": "3"},
        {"source": "test", "source_id": "1"},
    ]

    result = deduplicate_leads(leads)

    assert [
        lead["source_id"]
        for lead in result
    ] == ["1", "2", "3"]


def test_deduplicate_returns_copies():
    lead = {
        "source": "test",
        "source_id": "1",
        "company": "Acme",
    }

    result = deduplicate_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_duplicate_count():
    leads = [
        {"source": "test", "source_id": "1"},
        {"source": "test", "source_id": "1"},
        {"source": "test", "source_id": "2"},
        {"source": "test", "source_id": "2"},
        {"source": "test", "source_id": "3"},
    ]

    assert duplicate_count(leads) == 2


def test_duplicate_count_without_duplicates():
    leads = [
        {"source": "test", "source_id": "1"},
        {"source": "test", "source_id": "2"},
    ]

    assert duplicate_count(leads) == 0


def test_empty_dedupe():
    assert deduplicate_leads([]) == []
    assert duplicate_count([]) == 0


def test_dedupe_accepts_generators():
    leads = (
        {
            "source": "test",
            "source_id": str(index),
        }
        for index in range(3)
    )

    result = deduplicate_leads(leads)

    assert len(result) == 3
