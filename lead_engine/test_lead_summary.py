from .lead_summary import summarize_leads


def test_summarize_total():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
    ]

    result = summarize_leads(leads)

    assert result["total"] == 3


def test_summarize_routes():
    leads = [
        {"route": "Shiftr"},
        {"route": "Paxus"},
        {"route": "Shiftr"},
        {"route": "Thorio"},
    ]

    result = summarize_leads(leads)

    assert result["routes"] == {
        "Shiftr": 2,
        "Paxus": 1,
        "Thorio": 1,
    }


def test_summarize_statuses():
    leads = [
        {"status": "new"},
        {"status": "qualified"},
        {"status": "new"},
    ]

    result = summarize_leads(leads)

    assert result["statuses"] == {
        "new": 2,
        "qualified": 1,
    }


def test_summarize_priorities():
    leads = [
        {"priority": "High"},
        {"priority": "Critical"},
        {"priority": "High"},
        {"priority": "Low"},
    ]

    result = summarize_leads(leads)

    assert result["priorities"] == {
        "High": 2,
        "Critical": 1,
        "Low": 1,
    }


def test_summarize_ignores_blank_values():
    leads = [
        {
            "route": "",
            "status": "",
            "priority": "",
        },
        {
            "route": "Shiftr",
            "status": "new",
            "priority": "High",
        },
    ]

    result = summarize_leads(leads)

    assert result["routes"] == {"Shiftr": 1}
    assert result["statuses"] == {"new": 1}
    assert result["priorities"] == {"High": 1}


def test_summarize_strips_values():
    leads = [
        {
            "route": " Shiftr ",
            "status": " new ",
            "priority": " High ",
        },
    ]

    result = summarize_leads(leads)

    assert result["routes"] == {"Shiftr": 1}
    assert result["statuses"] == {"new": 1}
    assert result["priorities"] == {"High": 1}


def test_summarize_empty():
    assert summarize_leads([]) == {
        "total": 0,
        "routes": {},
        "statuses": {},
        "priorities": {},
    }


def test_summarize_accepts_generator():
    leads = (
        {"route": "Shiftr"}
        for _ in range(3)
    )

    result = summarize_leads(leads)

    assert result["total"] == 3
    assert result["routes"] == {"Shiftr": 3}
