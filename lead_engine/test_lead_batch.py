import pytest

from .lead_batch import (
    batch_count,
    batch_leads,
)


def test_batch_leads_splits_records():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
        {"company": "D"},
        {"company": "E"},
    ]

    result = batch_leads(leads, 2)

    assert result == [
        [{"company": "A"}, {"company": "B"}],
        [{"company": "C"}, {"company": "D"}],
        [{"company": "E"}],
    ]


def test_batch_leads_preserves_order():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
    ]

    result = batch_leads(leads, 10)

    assert [lead["company"] for lead in result[0]] == [
        "A",
        "B",
        "C",
    ]


def test_batch_leads_empty_input():
    assert batch_leads([], 10) == []


def test_batch_leads_rejects_invalid_size():
    with pytest.raises(ValueError):
        batch_leads([{"company": "A"}], 0)


def test_batch_leads_copies_records():
    lead = {"company": "Acme"}

    result = batch_leads([lead], 1)

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


def test_batch_count_exact_multiple():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
        {"company": "D"},
    ]

    assert batch_count(leads, 2) == 2


def test_batch_count_empty():
    assert batch_count([], 10) == 0


def test_batch_count_rejects_invalid_size():
    with pytest.raises(ValueError):
        batch_count([{"company": "A"}], 0)
