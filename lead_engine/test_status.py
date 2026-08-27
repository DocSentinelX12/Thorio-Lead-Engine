from .database import LeadDB
from .status import get_engine_status, get_sync_status


def test_engine_status_reports_empty_database(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    status = get_engine_status(db)

    assert status["total_leads"] == 0
    assert status["synced_leads"] == 0
    assert status["pending_leads"] == 0
    assert status["healthy"] is True


def test_engine_status_reports_pending_leads(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    db.insert_if_new(
        {
            "fingerprint": "status-001",
            "company": "Status Corp",
            "signal": "remote developer",
            "qualified": False,
            "status": "Unverified",
        }
    )

    status = get_engine_status(db)

    assert status["total_leads"] == 1
    assert status["synced_leads"] == 0
    assert status["pending_leads"] == 1
    assert status["healthy"] is False


def test_sync_status_reports_counts(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    db.insert_if_new(
        {
            "fingerprint": "status-002",
            "company": "Sync Corp",
            "signal": "developer",
        }
    )

    db.mark_synced(
        "status-002"
    )

    result = get_sync_status(db)

    assert result["total"] == 1
    assert result["synced"] == 1
    assert result["pending"] == 0
