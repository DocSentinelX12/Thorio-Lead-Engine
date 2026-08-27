import pytest

from .lead_pipeline import (
    process_leads,
    top_leads,
)


def make_lead(company, score):
    return {
        "company": company,
        "lead_score": score,
    }


def test_process_leads_prepares_leads():
    result = process_leads(
        [make_lead("Acme", 90)]
    )

    assert result[0]["company"] == "Acme"
    assert result[0]["priority"] == "Critical"


def test_process_leads_filters_by_score():
    leads = [
        make_lead("A", 90),
        make_lead("B", 40),
        make_lead("C", 70),
    ]

    result = process_leads(
        leads,
        minimum_score=70,
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "C"]


def test_process_leads_sorts_by_score():
    leads = [
        make_lead("A", 50),
        make_lead("B", 90),
        make_lead("C", 70),
    ]

    result = process_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "C", "A"]


def test_process_leads_empty():
    assert process_leads([]) == []


def test_top_leads_limits_results():
    leads = [
        make_lead("A", 50),
        make_lead("B", 90),
        make_lead("C", 80),
        make_lead("D", 70),
    ]

    result = top_leads(leads, limit=2)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "C"]


def test_top_leads_applies_minimum_score():
    leads = [
        make_lead("A", 95),
        make_lead("B", 85),
        make_lead("C", 50),
    ]

    result = top_leads(
        leads,
        limit=10,
        minimum_score=80,
    )

    assert [
        lead["company"]
        for lead in result
    ] == ["A", "B"]


def test_top_leads_zero_limit():
    leads = [
        make_lead("A", 90),
    ]

    assert top_leads(leads, limit=0) == []


def test_top_leads_negative_limit():
    with pytest.raises(ValueError):
        top_leads([], limit=-1)


def test_pipeline_does_not_mutate():
    lead = make_lead("Acme", 90)

    process_leads([lead])

    assert "priority" not in lead
