from unittest.mock import patch

from lead_engine.airtable_sync import sync_lead_if_missing


def test_new_lead_enters_review_without_delivery_approval():
    lead = {
        "company": "Approval State Corp",
        "source": "company website",
        "url": "https://example.com/careers",
        "signal": "Remote software engineering",
        "evidence": "Company is hiring remote software engineers.",
        "fingerprint": "approval-state-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
        "qualified": True,
        "lead_score": 90,
    }

    with patch(
        "lead_engine.airtable_sync.find_by_fingerprint",
        return_value=[],
    ), patch(
        "lead_engine.airtable_sync._request",
        return_value={
            "records": [
                {
                    "id": "rec_approval_001",
                    "fields": {},
                }
            ]
        },
    ) as mock_request:
        result = sync_lead_if_missing(lead)

    assert result["status"] == "created"

    payload = mock_request.call_args.args[2]
    fields = payload["records"][0]["fields"]

    assert fields["Review Status"] == "Qualified"
    assert fields["Outreach Status"] == "Not Contacted"
    assert fields["Qualified Lead?"] is True
    assert fields["Applicable Routes"] == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]
