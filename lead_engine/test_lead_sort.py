from .lead_sort import sort_leads


def test_sort_leads_by_priority():
    leads = [
        {
            "company": "Low",
            "priority": "Low",
            "lead_score": 90,
        },
        {
            "company": "High",
            "priority": "High",
            "lead_score": 50,
        },
        {
            "company": "Medium",
            "priority": "Medium",
            "lead_score": 70,
        },
    ]

    result = sort_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "High",
        "Medium",
        "Low",
    ]


def test_sort_leads_uses_score_with_same_priority():
    leads = [
        {
            "company": "A",
            "priority": "High",
            "lead_score": 60,
        },
        {
            "company": "B",
            "priority": "High",
            "lead_score": 90,
        },
        {
            "company": "C",
            "priority": "High",
            "lead_score": 75,
        },
    ]

    result = sort_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == [
        "B",
        "C",
        "A",
    ]


def test_sort_leads_handles_missing_priority():
    leads = [
        {
            "company": "A",
            "lead_score": 100,
        },
        {
            "company": "B",
            "priority": "Low",
            "lead_score": 10,
        },
    ]

    result = sort_leads(leads)

    assert result[0]["company"] == "B"
    assert result[1]["company"] == "A"


def test_sort_leads_handles_invalid_score():
    leads = [
        {
            "company": "A",
            "priority": "High",
            "lead_score": "not-a-number",
        },
        {
            "company": "B",
            "priority": "High",
            "lead_score": 50,
        },
    ]

    result = sort_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "A"]


def test_sort_leads_does_not_mutate_records():
    lead = {
        "company": "Acme",
        "priority": "High",
        "lead_score": 90,
    }

    result = sort_leads([lead])

    assert result[0] == lead
    assert result[0] is not lead


def test_sort_empty_leads():
    assert sort_leads([]) == []


def test_priority_matching_is_case_insensitive():
    leads = [
        {
            "company": "A",
            "priority": "low",
            "lead_score": 100,
        },
        {
            "company": "B",
            "priority": " HIGH ",
            "lead_score": 1,
        },
    ]

    result = sort_leads(leads)

    assert [
        lead["company"]
        for lead in result
    ] == ["B", "A"]
