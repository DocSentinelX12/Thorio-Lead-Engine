from .database import LeadDB
from .work_queue_service import (
    get_next_work_item,
    get_work_queue,
)


def test_work_queue_service_reads_local_database(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    db.insert_if_new(
        {
            "fingerprint": "service-001",
            "company": "Low Corp",
            "signal": "remote role",
            "lead_score": 3,
            "priority": "Low",
            "qualified": False,
            "status": "Unverified",
        }
    )

    db.insert_if_new(
        {
            "fingerprint": "service-002",
            "company": "High Corp",
            "signal": "remote software engineer",
            "lead_score": 12,
            "priority": "High",
            "qualified": False,
            "status": "Unverified",
        }
    )

    queue = get_work_queue(db)

    assert len(queue) == 2
    assert queue[0]["company"] == "High Corp"
    assert queue[0]["_fingerprint"] == "service-002"


def test_work_queue_service_returns_next_item(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    db.insert_if_new(
        {
            "fingerprint": "service-003",
            "company": "Medium Corp",
            "signal": "developer",
            "lead_score": 5,
            "priority": "Medium",
            "qualified": False,
            "status": "Unverified",
        }
    )

    result = get_next_work_item(db)

    assert result is not None
    assert result["company"] == "Medium Corp"
    assert result["_fingerprint"] == "service-003"


def test_work_queue_service_does_not_return_synced_leads(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    db.insert_if_new(
        {
            "fingerprint": "service-004",
            "company": "Synced Corp",
            "signal": "remote developer",
            "lead_score": 10,
            "priority": "High",
            "qualified": False,
            "status": "Unverified",
        }
    )

    db.mark_synced("service-004")

    result = get_next_work_item(db)

    assert result is None
