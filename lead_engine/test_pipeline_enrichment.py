from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline


def test_pipeline_enriches_lead_before_sync(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db)

    with patch("lead_engine.pipeline.sync_one") as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_enrichment_001"
            },
            "error": None,
        }

        result = pipeline.process(
            source="linkedin",
            source_id="enrichment-001",
            url="https://example.com/jobs/enrichment-001",
            company="Acme",
            signal="remote software engineer",
            evidence="Acme is hiring a remote software engineer.",
            contact_name=" Jane Smith ",
            contact_title=" CTO ",
            contact_email=" jane@example.com ",
        )

    assert result["accepted"] is True
    assert result["sync_status"] == "synced"

    assert result["lead"]["contact_name"] == "Jane Smith"
    assert result["lead"]["contact_title"] == "CTO"
    assert result["lead"]["contact_email"] == "jane@example.com"
    assert result["lead"]["enrichment_status"] == "enriched"


def test_pipeline_does_not_change_route_during_enrichment(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db)

    with patch("lead_engine.pipeline.sync_one") as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_enrichment_002"
            },
            "error": None,
        }

        result = pipeline.process(
            source="linkedin",
            source_id="enrichment-002",
            url="https://example.com/jobs/enrichment-002",
            company="Acme",
            signal="remote software engineer",
            evidence="Acme is hiring a remote software engineer.",
        )

    assert result["accepted"] is True
    assert result["lead"]["route"] == "Shiftr"
    assert result["lead"]["potential_routes"] == ["Shiftr", "Thorio"]
