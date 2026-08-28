import json
from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline
from .sync_worker import sync_pending


def test_failed_sync_stays_local_and_can_retry(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "failed",
            "lead": {},
            "airtable_record": None,
            "error": "Airtable unavailable",
        }

        result = pipeline.process(
            source="test",
            source_id="reliability-001",
            url="https://example.com/jobs/reliability-001",
            company="Reliability Corp",
            signal="remote software engineer",
            evidence="Remote software engineer opening found.",
        )

    assert result["accepted"] is True
    assert result["sync_status"] == "failed"

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "created",
            "record": {
                "id": "rec_retry_001"
            },
        }

        retry_result = sync_pending(db)

    assert retry_result["synced_count"] == 1
    assert retry_result["failed_count"] == 0

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0


def test_sync_pending_rejects_non_object_payload(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "failed",
            "lead": {},
            "airtable_record": None,
            "error": "Airtable unavailable",
        }

        result = pipeline.process(
            source="test",
            source_id="invalid-payload-001",
            url="https://example.com/jobs/invalid-payload-001",
            company="Invalid Payload Corp",
            signal="remote software engineer",
            evidence="Remote software engineer opening found.",
        )

    assert result["accepted"] is True
    assert result["sync_status"] == "failed"

    fingerprint = result["fingerprint"]

    current = db.get(fingerprint)

    assert current is not None

    db.update_payload(
        fingerprint,
        {
            "payload": json.dumps(
                [
                    "not",
                    "a",
                    "lead",
                ]
            )
        },
    )

    result = sync_pending(db)

    assert result["synced_count"] == 0
    assert result["already_exists_count"] == 0
    assert result["failed_count"] == 1

    assert (
        result["failed"][0]["error"]
        == "Invalid stored lead payload: expected an object."
    )

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1
