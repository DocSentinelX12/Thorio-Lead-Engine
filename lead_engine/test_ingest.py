from unittest.mock import patch

from .database import LeadDB
from .ingest import LeadIngestor
from .pipeline import LeadPipeline


def test_ingestor_sends_lead_to_pipeline(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)
    ingestor = LeadIngestor(pipeline)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_ingest_001"
            },
            "error": None,
        }

        result = ingestor.ingest_one(
            {
                "source": " linkedin ",
                "source_id": "ingest-001",
                "url": "https://example.com/jobs/ingest-001",
                "company": "Acme",
                "signal": "remote software engineer",
                "evidence": "Remote engineering opening.",
            }
        )

    assert result["accepted"] is True
    assert result["sync_status"] == "synced"
    assert result["lead"]["company"] == "Acme"
    assert result["lead"]["route"] == "Shiftr"
    assert "Thorio" in result["lead"]["potential_routes"]

    assert db.stats()[0] == 1

    mock_sync.assert_called_once()


def test_ingestor_handles_multiple_leads(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)
    ingestor = LeadIngestor(pipeline)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_ingest_batch"
            },
            "error": None,
        }

        results = ingestor.ingest_many(
            [
                {
                    "source": "linkedin",
                    "source_id": "batch-001",
                    "url": "https://example.com/jobs/001",
                    "company": "Acme",
                    "signal": "remote developer",
                    "evidence": "Developer opening.",
                },
                {
                    "source": "company-site",
                    "source_id": "batch-002",
                    "url": "https://example.com/jobs/002",
                    "company": "Example Corp",
                    "signal": "software engineer",
                    "evidence": "Engineering opening.",
                },
            ]
        )

    assert len(results) == 2
    assert all(result["accepted"] is True for result in results)
    assert db.stats()[0] == 2
    assert mock_sync.call_count == 2
