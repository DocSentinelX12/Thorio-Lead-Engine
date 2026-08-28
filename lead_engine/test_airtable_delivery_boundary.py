from unittest.mock import patch

from lead_engine.airtable_approval import read_approval


def test_airtable_approval_does_not_directly_send_lead():
    lead = {
        "company": "Boundary Test Corp",
        "fingerprint": "boundary-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_boundary_001",
        "fields": {
            "Review Status": "Qualified",
            "Applicable Routes": [
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
            "rec_boundary_001",
        )

    assert result["status"] == "approved"

    approved = result["lead"]

    assert approved["approval_status"] == "approved"
    assert approved["human_approved"] is True

    assert approved["approved_routes"] == [
        "Shiftr",
    ]

    assert approved.get("delivered") is not True
    assert approved.get("delivery_status") != "delivered"


def test_pending_airtable_review_cannot_enter_delivery():
    lead = {
        "company": "Pending Boundary Corp",
        "fingerprint": "boundary-002",
        "potential_routes": [
            "Paxus",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_boundary_002",
        "fields": {
            "Review Status": "Reviewing",
            "Applicable Routes": [
                "Paxus",
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
            "rec_boundary_002",
        )

    assert result["status"] == "pending"
    assert result["lead"] == lead


def test_rejected_airtable_lead_cannot_enter_delivery():
    lead = {
        "company": "Rejected Boundary Corp",
        "fingerprint": "boundary-003",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_boundary_003",
        "fields": {
            "Review Status": "Rejected",
            "Applicable Routes": [
                "Paxus",
                "Shiftr",
                "Thorio",
            ],
            "Reason Not Qualified": "Not a qualified prospect.",
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=airtable_record,
    ):
        result = read_approval(
            lead,
            "rec_boundary_003",
        )

    assert result["status"] == "rejected"

    rejected = result["lead"]

    assert rejected["approval_status"] == "rejected"
    assert rejected["human_approved"] is False
    assert rejected.get("delivered") is not True
