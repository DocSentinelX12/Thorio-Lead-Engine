import pytest

from .lead_selection import (
    select_leads,
    select_top_lead,
)


def make_lead(company, score, priority="High"):
    return {
        "company": company,
        "lead_score": score,
        "priority": priority,
    }


def test_select_leads_ranks_before_limiting():
    leads = [
        make_lead("Low", 50, "Low"),
        make_lead("Critical", 80, "Critical"),
        make_lead("High", 95, "High"),
    ]

    result = select_leads(leads, limit=2)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "Critical",
        "High",
    ]


def test_select_leads_without_limit():
    leads = [
        make_lead("A", 70),
        make_lead("B", 90),
    ]

    result = select_leads(leads)

    assert len(result) == 2
    assert result[0]["company"] == "B"


def test_select_leads_limit_zero():
    leads = [
        make_lead("A", 100),
    ]

    assert select_leads(leads, limit=0) == []


def test_select_leads_negative_limit_raises():
    with pytest.raises(ValueError):
        select_leads([], limit=-1)


def test_select_leads_empty():
    assert select_leads([]) == []


def test_select_top_lead():
    leads = [
        make_lead("A", 60),
        make_lead("B", 95),
        make_lead("C", 80),
    ]

    result = select_top_lead(leads)

    assert result["company"] == "B"


def test_select_top_lead_empty():
    assert select_top_lead([]) is None


def test_select_leads_accepts_generator():
    leads = (
        make_lead(f"Company {i}", i)
        for i in range(5)
    )

    result = select_leads(leads, limit=2)

    assert len(result) == 2
    assert result[0]["lead_score"] == 4
    assert result[1]["lead_score"] == 3
