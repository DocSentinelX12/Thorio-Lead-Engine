from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline


def test_pipeline_routes_and_persists_lead(tmp_path):
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
                "id": "rec_test_123"
            },
            "error": None,
        }

        result = pipeline.process(
            source="test",
            source_id="acme-001",
            url="https://example.com/jobs/acme-001",
            company="Acme",
            signal="remote software engineer",
            evidence=(
                "Company careers page says they are hiring "
                "a remote software engineer."
            ),
        )

    assert result["status"] == "accepted"
    assert result["accepted"] is True
    assert result["lead"]["route"] == "Thorio"
    assert "Shiftr" in result["potential_routes"]
    assert "Thorio" in result["potential_routes"]
    assert result["sync_status"] == "synced"

    pending = db.pending()

    assert len(pending) == 0

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0

    mock_sync.assert_called_once()


def test_pipeline_does_not_lose_lead_when_sync_fails(tmp_path):
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
            source_id="example-001",
            url="https://example.com/jobs/example-001",
            company="Example Corp",
            signal="remote developer",
            evidence="Remote developer opening found.",
        )

    assert result["status"] == "accepted"
    assert result["sync_status"] == "failed"
    assert result["sync_error"] == "Airtable unavailable"

    pending = db.pending()

    assert len(pending) == 1

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1

    mock_sync.assert_called_once()


def test_paxus_submission_marks_revenue_opportunity_referred(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    lead = {
        "fingerprint": "paxus-referred-lifecycle",
        "company": "Acme Corp",
        "contact_name": "Jane Smith",
        "contact_email": "jane@example.com",
        "qualified": True,
        "potential_routes": ["Paxus"],
        "eligible_routes": ["Paxus"],
        "preserved_routes": ["Paxus"],
        "contact_communicated": True,
        "contact_consent": True,
        "warm_referral_ready": True,
        "referral_submitted": False,
        "revenue_lifecycle_state": "conversation_active",
        "outreach_state": "awaiting_response",
        "next_follow_up_at": "2026-09-20T12:00:00+00:00",
        "follow_up_due": True,
    }
    db.insert_if_new(lead)
    pipeline = LeadPipeline(db=db, sync_enabled=False)

    stored = pipeline.submit_paxus_referral(lead["fingerprint"])

    assert stored["revenue_lifecycle_state"] == "referred"
    assert stored["outreach_state"] == "referred"
    assert stored["outreach_stop_reason"] == "referred"
    assert stored["next_follow_up_at"] is None
    assert stored["follow_up_due"] is False
    assert stored["commercial_outcome"]["type"] == "referred"
    assert stored["referral_submitted"] is True
