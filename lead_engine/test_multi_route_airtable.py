from unittest.mock import patch

from lead_engine.airtable_sync import sync_lead_if_missing


def test_multi_route_lead_preserves_paxus_shiftr_and_thorio():
    lead = {
        "company": "Multi Route Technologies",
        "source": "company website",
        "url": "https://example.com/careers",
        "signal": "Remote software engineering and AI hiring",
        "evidence": "Company is hiring remote engineers and expanding AI operations.",
        "fingerprint": "multi-route-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
        "qualified": True,
        "lead_score": 95,
        "evidence_status": "Verified",
    }

    with patch(
        "lead_engine.airtable_sync.find_by_fingerprint",
        return_value=[],
    ), patch(
        "lead_engine.airtable_sync._request",
        return_value={
            "records": [
                {
                    "id": "rec_multi_route_001",
                    "fields": {},
                }
            ]
        },
    ) as mock_request:
        result = sync_lead_if_missing(lead)

    assert result["status"] == "created"

    payload = mock_request.call_args.args[2]
    fields = payload["records"][0]["fields"]

    assert fields["Applicable Routes"] == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]

    assert fields["Recommended Partner"] == "Both"

    assert fields["Qualified Lead?"] is True
    assert fields["Evidence Status"] == "Verified"

    assert fields["Outreach Status"] == "Not Contacted"
