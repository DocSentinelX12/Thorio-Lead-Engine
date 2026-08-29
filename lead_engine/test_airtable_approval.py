from unittest.mock import patch

from lead_engine.airtable_approval import read_approval


def test_airtable_approval_approves_only_selected_routes():
    lead = {
        "company": "Route Control Corp",
        "fingerprint": "route-control-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_route_control_001",
        "fields": {
            "Review Status": "Qualified",
            "Applicable Routes": [
                "Shiftr",
                "Thorio",
            ],
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=airtable_record,
    ):
        result = read_approval(
            lead,
            "rec_route_control_001",
        )

    assert result["status"] == "approved"

    approved = result["lead"]

    assert approved["approval_status"] == "approved"
    assert approved["human_approved"] is True
    assert approved["approval_required"] is False

    assert approved["approved_routes"] == [
        "Shiftr",
        "Thorio",
    ]

    assert "Paxus" not in approved["approved_routes"]


def test_airtable_rejection_never_authorizes_delivery():
    lead = {
        "company": "Rejected Corp",
        "fingerprint": "rejected-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_rejected_001",
        "fields": {
            "Review Status": "Rejected",
            "Applicable Routes": [
                "Paxus",
                "Shiftr",
                "Thorio",
            ],
            "Reason Not Qualified": "Insufficient evidence.",
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=airtable_record,
    ):
        result = read_approval(
            lead,
            "rec_rejected_001",
        )

    assert result["status"] == "rejected"

    rejected = result["lead"]

    assert rejected["approval_status"] == "rejected"
    assert rejected["human_approved"] is False
    assert rejected["approval_required"] is False

    assert rejected["rejection_reason"] == (
        "Insufficient evidence."
    )


def test_airtable_pending_state_does_not_authorize_delivery():
    lead = {
        "company": "Pending Corp",
        "fingerprint": "pending-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
        ],
    }

    airtable_record = {
        "id": "rec_pending_001",
        "fields": {
            "Review Status": "Reviewing",
            "Applicable Routes": [
                "Paxus",
                "Shiftr",
            ],
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=airtable_record,
    ):
        result = read_approval(
            lead,
            "rec_pending_001",
        )

    assert result["status"] == "pending"
    assert result["lead"] == lead


def test_airtable_record_is_reconstructed_into_canonical_lead():
    from lead_engine.airtable_approval import (
        airtable_record_to_lead,
    )

    record = {
        "id": "rec_123",
        "fields": {
            "Company": "Example Corp",
            "Signal": "technology engineering project",
            "Source URL": "https://example.com/job",
            "Source Platform": "LinkedIn",
            "Decision Maker": "Jane Smith",
            "Title": "CTO",
            "Duplicate Key": "example-123",
            "Lead Score": 75,
            "Qualified Lead?": True,
            "Why This Lead": "Confirmed technology need.",
            "Evidence Status": "Verified",
            "Applicable Routes": [
                "Shiftr",
                "Thorio",
            ],
            "Review Status": "Reviewing",
        },
    }

    lead = airtable_record_to_lead(
        record
    )

    assert lead["airtable_record_id"] == "rec_123"
    assert lead["company"] == "Example Corp"
    assert lead["fingerprint"] == "example-123"
    assert lead["lead_score"] == 75
    assert lead["qualified"] is True
    assert lead["potential_routes"] == [
        "Shiftr",
        "Thorio",
    ]


def test_fetch_approval_candidates_paginates_all_records():
    from lead_engine.airtable_approval import (
        fetch_approval_candidates,
    )

    responses = [
        {
            "records": [
                {
                    "id": "rec_1",
                    "fields": {
                        "Company": "One",
                        "Duplicate Key": "one",
                    },
                }
            ],
            "offset": "next-page",
        },
        {
            "records": [
                {
                    "id": "rec_2",
                    "fields": {
                        "Company": "Two",
                        "Duplicate Key": "two",
                    },
                }
            ]
        },
    ]

    with patch(
        "lead_engine.airtable_approval._request",
        side_effect=responses,
    ) as request:
        result = fetch_approval_candidates()

    assert [
        item["record_id"]
        for item in result
    ] == [
        "rec_1",
        "rec_2",
    ]

    assert request.call_count == 2


def test_fetch_approval_candidates_skips_invalid_records():
    from lead_engine.airtable_approval import (
        fetch_approval_candidates,
    )

    with patch(
        "lead_engine.airtable_approval.list_records",
        return_value=[
            {
                "id": "rec_valid",
                "fields": {
                    "Company": "Valid",
                },
            },
            {
                "fields": {
                    "Company": "Missing ID",
                },
            },
            "invalid",
        ],
    ):
        result = fetch_approval_candidates()

    assert len(result) == 1
    assert result[0]["record_id"] == "rec_valid"
