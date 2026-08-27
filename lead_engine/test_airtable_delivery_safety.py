from unittest.mock import patch

from lead_engine.airtable_sync import sync_lead_if_missing


def test_airtable_sync_does_not_approve_delivery():
    lead = {
        "company": "Safety Test Corp",
        "source": "linkedin",
        "url": "https://example.com/job",
        "signal": "Remote software engineer",
        "evidence": "Remote engineering role found.",
        "fingerprint": "safety-test-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
        "qualified": True,
    }

    with patch(
        "lead_engine.airtable_sync.find_by_fingerprint",
        return_value=[],
    ), patch(
        "lead_engine.airtable_sync._request",
        return_value={
            "records": [
                {
                    "id": "rec_safety_001",
                    "fields": {},
                }
            ]
        },
    ) as mock_request:
        result = sync_lead_if_missing(lead)

    assert result["status"] == "created"

    payload = mock_request.call_args.args[2]

    fields = payload["records"][0]["fields"]

    assert fields["Qualified Lead?"] is True

    assert "Approved to Contact" not in fields.values()
    assert "Contacted" not in fields.values()

    assert fields["Outreach Status"] == "Not Contacted"
