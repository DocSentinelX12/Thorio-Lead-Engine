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
