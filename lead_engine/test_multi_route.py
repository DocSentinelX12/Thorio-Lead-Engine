from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline


def test_lead_preserves_multiple_potential_routes(tmp_path):
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
                "id": "rec_multi_001"
            },
            "error": None,
        }

        result = pipeline.process(
            source="test",
            source_id="multi-route-001",
            url="https://example.com/jobs/multi-route-001",
            company="Acme",
            signal="remote software engineer",
            evidence=(
                "Acme is hiring a remote software engineer."
            ),
        )

    assert result["accepted"] is True

    assert result["lead"]["route"] == "Shiftr"

    assert "Shiftr" in result["lead"]["potential_routes"]
    assert "Thorio" in result["lead"]["potential_routes"]

    stored = db.pending()

    assert len(stored) == 0

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0

    mock_sync.assert_called_once()
