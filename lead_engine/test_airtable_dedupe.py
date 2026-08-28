from unittest.mock import patch

from lead_engine.airtable_sync import sync_lead_if_missing


def test_existing_fingerprint_prevents_duplicate_creation():
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
        "lead_engine.airtable_sync._request"
    ) as mock_request:
        result = sync_lead_if_missing(lead)

    assert result["status"] == "already_exists"
    assert result["record"] == existing_record

    mock_request.assert_not_called()
