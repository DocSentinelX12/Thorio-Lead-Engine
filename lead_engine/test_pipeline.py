from unittest.mock import patch

from .pipeline import LeadPipeline
from .queue import LeadQueue


def test_pipeline_routes_and_persists_lead(tmp_path):
    queue = LeadQueue(
        db_path=str(tmp_path / "test_leads.db")
    )

    pipeline = LeadPipeline(queue=queue)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_test_123"
            },
            "error": None,
        }

        result = pipeline.process(
            company="Acme",
            signal="remote software engineer",
            evidence="Company careers page says they are hiring a remote software engineer.",
            duplicate_key="acme|remote-software-engineer",
        )

    assert result["recommended_partner"] == "Shiftr"
    assert result["sync_status"] == "synced"

    stored = queue.get(
        result["lead"]["_queue_id"]
    )

    assert stored is not None
    assert stored["company"] == "Acme"
    assert stored["recommended_partner"] == "Shiftr"
    assert stored["review_status"] == "Review"
    assert stored["qualified"] is False

    mock_sync.assert_called_once()


def test_pipeline_does_not_lose_lead_when_sync_fails(tmp_path):
    queue = LeadQueue(
        db_path=str(tmp_path / "failed_leads.db")
    )

    pipeline = LeadPipeline(queue=queue)

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
            company="Example Corp",
            signal="remote developer",
            evidence="Remote developer opening found.",
            duplicate_key="example-corp|remote-developer",
        )

    assert result["sync_status"] == "failed"

    stored = queue.get(
        result["lead"]["_queue_id"]
    )

    assert stored is not None
    assert stored["company"] == "Example Corp"
    assert stored["_sync_status"] == "failed"
    assert stored["_last_sync_error"] == "Airtable unavailable"
