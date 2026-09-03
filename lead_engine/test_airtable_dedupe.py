from unittest.mock import patch

from lead_engine.airtable_sync import sync_lead_if_missing


def test_existing_fingerprint_updates_existing_record_without_duplicate_creation():
    lead = {
        "company": "Duplicate Prevention Corp",
        "source": "company website",
        "url": "https://example.com/careers",
        "signal": "Remote software engineer",
        "evidence": "Remote engineering role found.",
        "fingerprint": "duplicate-test-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    existing_record = {
        "id": "rec_existing_001",
        "fields": {
            "Company": "Duplicate Prevention Corp",
            "Duplicate Key": "duplicate-test-001",
        },
    }

    with patch(
        "lead_engine.airtable_sync.find_by_fingerprint",
        return_value=[existing_record],
    ), patch(
        "lead_engine.airtable_sync.update_master_record",
        return_value={
            "records": [
                existing_record
            ]
        },
    ) as mock_update, patch(
        "lead_engine.airtable_sync.create_master_record"
    ) as mock_create:

        result = sync_lead_if_missing(lead)

    assert result["status"] == "updated"
    assert result["record"] == existing_record

    mock_update.assert_called_once()
    mock_create.assert_not_called()
