from unittest.mock import patch

from .database import LeadDB
from .sync_worker import sync_pending


def test_sync_worker_retries_failed_lead(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    lead = {
        "source": "test",
        "source_id": "worker-001",
        "url": "https://example.com/jobs/worker-001",
        "company": "Worker Corp",
        "signal": "remote developer",
        "evidence": "Remote developer opening found.",
        "route": "Shiftr",
        "potential_routes": [
            "Shiftr",
            "Thorio",
        ],
        "status": "Unverified",
        "fingerprint": "worker-fingerprint-001",
    }

    db.insert_if_new(lead)

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync:
        mock_sync.side_effect = Exception(
            "Airtable temporarily unavailable"
        )

        first_result = sync_pending(db)

    assert first_result["synced_count"] == 0
    assert first_result["failed_count"] == 1

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync, patch(
        "lead_engine.sync_worker.sync_outreach"
    ) as mock_outreach, patch(
        "lead_engine.sync_worker.sync_followup"
    ) as mock_followup:

        mock_sync.return_value = {
            "status": "created",
            "record": {
                "id": "rec_worker_001"
            },
        }

        mock_outreach.return_value = {
            "status": "created",
            "record": {
                "id": "outreach_001"
            },
        }

        mock_followup.return_value = {
            "status": "created",
            "record": {
                "id": "followup_001"
            },
        }

        second_result = sync_pending(db)

    assert second_result["synced_count"] == 1
    assert second_result["failed_count"] == 0

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0
