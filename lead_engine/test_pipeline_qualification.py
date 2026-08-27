from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline


def test_pipeline_human_qualification_persists(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_qualification_001"
            },
            "error": None,
        }

        result = pipeline.process(
            source="test",
            source_id="qualification-001",
            url="https://example.com/jobs/qualification-001",
            company="Acme",
            signal="remote software engineer",
            evidence="Remote software engineer opening.",
        )

    assert result["sync_status"] == "synced"
    assert result["lead"]["qualified"] is False

    fingerprint = result["fingerprint"]

    qualified = pipeline.qualify(
        fingerprint,
        qualified=True,
    )

    assert qualified["qualified"] is True
    assert qualified["status"] == "Qualified"
    assert qualified["review_status"] == "Qualified"

    stored = db.get(fingerprint)

    assert stored is not None
    assert stored["qualified"] is True
    assert stored["status"] == "Qualified"
    assert stored["review_status"] == "Qualified"


def test_pipeline_can_reject_lead_after_human_review(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "synced",
            "lead": {},
            "airtable_record": {
                "id": "rec_qualification_002"
            },
            "error": None,
        }

        result = pipeline.process(
            source="test",
            source_id="qualification-002",
            url="https://example.com/jobs/qualification-002",
            company="Example Corp",
            signal="remote developer",
            evidence="Remote developer opening.",
        )

    fingerprint = result["fingerprint"]

    rejected = pipeline.qualify(
        fingerprint,
        qualified=False,
        reason="No confirmed technology need.",
    )

    assert rejected["qualified"] is False
    assert rejected["status"] == "Not Qualified"
    assert rejected["review_status"] == "Not Qualified"
    assert rejected["reason_not_qualified"] == (
        "No confirmed technology need."
    )
