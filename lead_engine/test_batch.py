from unittest.mock import patch

from .batch import BatchProcessor
from .database import LeadDB
from .ingest import LeadIngestor
from .pipeline import LeadPipeline


def test_batch_processes_all_valid_leads(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)
    ingestor = LeadIngestor(pipeline)
    processor = BatchProcessor(ingestor)

    leads = [
        {
            "source": "linkedin",
            "source_id": "batch-001",
            "url": "https://example.com/jobs/001",
            "company": "Acme",
            "signal": "remote software engineer",
            "evidence": "Remote engineering opening.",
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

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_batch_001"
            },
            "error": None,
        }

        result = processor.process(leads)

    assert result["processed_count"] == 2
    assert result["failed_count"] == 0
    assert result["total"] == 2
    assert db.stats()[0] == 2
    assert mock_sync.call_count == 2


def test_batch_continues_after_invalid_lead(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)
    ingestor = LeadIngestor(pipeline)
    processor = BatchProcessor(ingestor)

    leads = [
        {
            "source": "linkedin",
            "source_id": "valid-001",
            "url": "https://example.com/jobs/001",
            "company": "Acme",
            "signal": "remote developer",
            "evidence": "Developer opening.",
        },
        {
            "source": "linkedin",
            "source_id": "invalid-001",
            "url": "",
            "company": "Broken Corp",
            "signal": "",
            "evidence": "",
        },
        {
            "source": "company-site",
            "source_id": "valid-002",
            "url": "https://example.com/jobs/002",
            "company": "Example Corp",
            "signal": "software engineer",
            "evidence": "Engineering opening.",
        },
    ]

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_batch_002"
            },
            "error": None,
        }

        result = processor.process(leads)

    assert result["processed_count"] == 2
    assert result["failed_count"] == 1
    assert result["total"] == 3

    assert db.stats()[0] == 2
    assert mock_sync.call_count == 2

    assert "error" in result["failed"][0]
