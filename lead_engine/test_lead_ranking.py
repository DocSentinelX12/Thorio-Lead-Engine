from .lead_ranking import (
    priority_score,
    rank_leads,
    ranking_score,
)


def test_ranking_score():
    assert ranking_score({"lead_score": 95}) == 95.0


def test_ranking_score_missing():
    assert ranking_score({}) == 0.0


def test_ranking_score_invalid():
    assert ranking_score({"lead_score": "invalid"}) == 0.0


def test_priority_score():
    assert priority_score({"priority": "Critical"}) == 4
    assert priority_score({"priority": "High"}) == 3
    assert priority_score({"priority": "Medium"}) == 2
    assert priority_score({"priority": "Low"}) == 1


def test_unknown_priority():
    assert priority_score({"priority": "Unknown"}) == 0


def test_rank_leads_by_priority():
    leads = [
        {"company": "Low", "priority": "Low", "lead_score": 100},
        {"company": "Critical", "priority": "Critical", "lead_score": 50},
        {"company": "High", "priority": "High", "lead_score": 90},
    ]

    result = rank_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "Critical",
        "High",
        "Low",
    ]


def test_rank_leads_uses_score_as_tiebreaker():
    leads = [
        {"company": "A", "priority": "High", "lead_score": 70},
        {"company": "B", "priority": "High", "lead_score": 95},
        {"company": "C", "priority": "High", "lead_score": 80},
    ]

    result = rank_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "B",
        "C",
        "A",
    ]


def test_rank_leads_returns_copies():
    lead = {
        "company": "Acme",
        "priority": "High",
        "lead_score": 90,
    }

    result = rank_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_rank_leads_accepts_generator():
    leads = (
        {
            "company": f"Company {index}",
            "priority": "High",
            "lead_score": index,
        }
        for index in range(3)
    )

    result = rank_leads(leads)

    assert len(result) == 3
    assert result[0]["lead_score"] == 2
