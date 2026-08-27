from .lead_summary import summarize_leads


def test_summarize_total():
    leads = [
        {"company": "A"},
        {"company": "B"},
        {"company": "C"},
    ]

    result = summarize_leads(leads)

    assert result["total"] == 3


def test_summarize_approved():
    leads = [
        {"company": "A", "delivery_status": "approved"},
        {"company": "B", "delivery_status": "pending"},
        {"company": "C", "delivery_status": "approved"},
    ]

    result = summarize_leads(leads)

    assert result["approved"] == 2


def test_summarize_routes():
    leads = [
        {"route": "Shiftr"},
        {"route": "Shiftr"},
        {"route": "Paxus"},
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
        {"status": "qualified"},
        {"status": "delivered"},
    ]

    result = summarize_leads(leads)

    assert result["statuses"] == {
        "new": 1,
        "qualified": 2,
        "delivered": 1,
    }


def test_summarize_ignores_blank_values():
    leads = [
        {
            "route": "",
            "status": "",
            "delivery_status": "",
        },
        {
            "route": "Shiftr",
            "status": "new",
        },
    ]

    result = summarize_leads(leads)

    assert result["total"] == 2
    assert result["approved"] == 0
    assert result["routes"] == {"Shiftr": 1}
    assert result["statuses"] == {"new": 1}


def test_summarize_empty_collection():
    result = summarize_leads([])

    assert result == {
        "total": 0,
        "approved": 0,
        "routes": {},
        "statuses": {},
    }


def test_summarize_accepts_generators():
    leads = (
        {"route": "Shiftr"}
        for _ in range(3)
    )

    result = summarize_leads(leads)

    assert result["total"] == 3
    assert result["routes"] == {"Shiftr": 3}
