import pytest

from .lead_batch_utils import (
    batch_count,
    batch_leads,
)


def make_lead(company, score):
    return {
        "company": company,
        "lead_score": score,
        "priority": "High",
    }


def test_batch_leads():
    leads = [
        make_lead("A", 90),
        make_lead("B", 80),
        make_lead("C", 70),
        make_lead("D", 60),
        make_lead("E", 50),
    ]

    result = batch_leads(leads, 2)

    assert [
        [lead["company"] for lead in batch]
        for batch in result
    ] == [
        ["A", "B"],
        ["C", "D"],
        ["E"],
    ]


def test_batch_leads_ranks_before_batching():
    leads = [
        make_lead("Low", 50),
        make_lead("High", 95),
        make_lead("Medium", 75),
    ]

    result = batch_leads(leads, 2)

    assert [
        [lead["company"] for lead in batch]
        for batch in result
    ] == [
        ["High", "Medium"],
        ["Low"],
    ]


def test_batch_leads_empty():
    assert batch_leads([], 2) == []


def test_batch_leads_exact_multiple():
    leads = [
        make_lead("A", 90),
        make_lead("B", 80),
        make_lead("C", 70),
        make_lead("D", 60),
    ]

    result = batch_leads(leads, 2)

    assert len(result) == 2
    assert all(len(batch) == 2 for batch in result)


def test_batch_leads_invalid_size():
    with pytest.raises(ValueError):
        batch_leads([], 0)

    with pytest.raises(ValueError):
        batch_leads([], -1)


def test_batch_count():
    leads = [
        make_lead("A", 90),
        make_lead("B", 80),
        make_lead("C", 70),
        make_lead("D", 60),
        make_lead("E", 50),
    ]

    assert batch_count(leads, 2) == 3


def test_batch_count_empty():
    assert batch_count([], 2) == 0


def test_batch_leads_returns_copies():
    lead = make_lead("Acme", 90)

    result = batch_leads([lead], 1)

    assert result[0][0] == lead
    assert result[0][0] is not lead


def test_batch_leads_accepts_generator():
    leads = (
        make_lead(f"Company {i}", i)
        for i in range(5)
    )

    result = batch_leads(leads, 2)

    assert len(result) == 3
    assert sum(len(batch) for batch in result) == 5
