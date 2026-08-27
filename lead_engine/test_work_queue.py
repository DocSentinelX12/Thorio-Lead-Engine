from .work_queue import build_work_queue, next_lead


def test_work_queue_prioritizes_high_score():
    leads = [
        {
            "company": "Low Corp",
            "lead_score": 3,
            "priority": "Low",
            "qualified": False,
            "status": "Unverified",
        },
        {
            "company": "High Corp",
            "lead_score": 12,
            "priority": "High",
            "qualified": False,
            "status": "Unverified",
        },
        {
            "company": "Medium Corp",
            "lead_score": 6,
            "priority": "Medium",
            "qualified": False,
            "status": "Unverified",
        },
    ]

    queue = build_work_queue(leads)

    assert queue[0]["company"] == "High Corp"
    assert queue[1]["company"] == "Medium Corp"
    assert queue[2]["company"] == "Low Corp"


def test_work_queue_excludes_qualified_leads():
    leads = [
        {
            "company": "Qualified Corp",
            "lead_score": 12,
            "priority": "High",
            "qualified": True,
            "status": "Qualified",
        },
        {
            "company": "Review Corp",
            "lead_score": 8,
            "priority": "High",
            "qualified": False,
            "status": "In Review",
        },
    ]

    queue = build_work_queue(leads)

    assert len(queue) == 1
    assert queue[0]["company"] == "Review Corp"


def test_work_queue_excludes_not_qualified_leads():
    leads = [
        {
            "company": "Rejected Corp",
            "lead_score": 12,
            "priority": "High",
            "qualified": False,
            "status": "Not Qualified",
        },
        {
            "company": "Review Corp",
            "lead_score": 5,
            "priority": "Medium",
            "qualified": False,
            "status": "In Review",
        },
    ]

    queue = build_work_queue(leads)

    assert len(queue) == 1
    assert queue[0]["company"] == "Review Corp"


def test_next_lead_returns_highest_priority():
    leads = [
        {
            "company": "Medium Corp",
            "lead_score": 6,
            "priority": "Medium",
            "qualified": False,
            "status": "Unverified",
        },
        {
            "company": "High Corp",
            "lead_score": 10,
            "priority": "High",
            "qualified": False,
            "status": "Unverified",
        },
    ]

    result = next_lead(leads)

    assert result is not None
    assert result["company"] == "High Corp"


def test_next_lead_returns_none_when_no_work_exists():
    leads = [
        {
            "company": "Qualified Corp",
            "lead_score": 10,
            "priority": "High",
            "qualified": True,
            "status": "Qualified",
        },
        {
            "company": "Rejected Corp",
            "lead_score": 8,
            "priority": "High",
            "qualified": False,
            "status": "Not Qualified",
        },
    ]

    assert next_lead(leads) is None
