from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline


def test_complete_lead_engine_flow(tmp_path):
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
                "id": "rec_integration_001"
            },
            "error": None,
        }

        result = pipeline.process(
            source="linkedin",
            source_id="integration-001",
            url="https://example.com/jobs/integration-001",
            company="Integration Corp",
            signal="remote software engineer",
            evidence=(
                "Integration Corp is hiring a remote "
                "software engineer."
            ),
        )

    assert result["accepted"] is True
    assert result["sync_status"] == "synced"

    assert result["lead"]["company"] == "Integration Corp"
    assert result["lead"]["route"] == "Shiftr"

    assert "Shiftr" in result["lead"]["potential_routes"]
    assert "Thorio" in result["lead"]["potential_routes"]

    assert result["lead"]["fingerprint"]

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0

    mock_sync.assert_called_once()
