import pytest

from .lead_batch_utils import (
    batch_count,
    chunk_leads,
)


def test_chunk_leads():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
        {"company": "D"},
        {"company": "E"},
    ]

    result = chunk_leads(leads, 2)

    assert [
        [lead["company"] for lead in batch]
        for batch in result
    ] == [
        ["A", "B"],
        ["C", "D"],
        ["E"],
    ]


def test_chunk_leads_exact_size():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
        {"company": "D"},
    ]

    result = chunk_leads(leads, 2)

    assert len(result) == 2
    assert all(len(batch) == 2 for batch in result)


def test_chunk_leads_empty():
    assert chunk_leads([], 10) == []


def test_chunk_leads_invalid_size():
    with pytest.raises(ValueError):
        chunk_leads([], 0)

    with pytest.raises(ValueError):
        chunk_leads([], -1)


def test_chunk_leads_preserves_order():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
    ]

    result = chunk_leads(leads, 10)

    assert [
        lead["company"]
        for lead in result[0]
    ] == ["A", "B", "C"]


def test_chunk_leads_returns_copies():
    lead = {"company": "Acme"}

    result = chunk_leads([lead], 1)

    assert result[0][0] == lead
    assert result[0][0] is not lead


def test_batch_count():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
        {"company": "D"},
        {"company": "E"},
    ]

    assert batch_count(leads, 2) == 3


def test_batch_count_exact():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
        {"company": "D"},
    ]

    assert batch_count(leads, 2) == 2
