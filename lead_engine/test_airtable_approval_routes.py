from unittest.mock import patch

from lead_engine.airtable_approval import read_approval


def test_shiftr_approval_does_not_approve_paxus_or_thorio():
    lead = {
        "company": "Independent Route Corp",
        "fingerprint": "independent-route-001",
        "potential_routes": [
            "Shiftr",
            "Paxus",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_independent_001",
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
            "rec_independent_001",
        )

    assert result["status"] == "approved"

    approved = result["lead"]

    assert approved["approved_routes"] == [
        "Shiftr",
    ]

    assert "Paxus" not in approved["approved_routes"]
    assert "Thorio" not in approved["approved_routes"]


def test_paxus_approval_does_not_approve_shiftr_or_thorio():
    lead = {
        "company": "Paxus Only Corp",
        "fingerprint": "paxus-only-001",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_paxus_only_001",
        "fields": {
            "Review Status": "Approved",
            "Applicable Routes": [
                "Paxus",
            ],
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=airtable_record,
    ):
        result = read_approval(
            lead,
            "rec_paxus_only_001",
        )

    approved = result["lead"]

    assert approved["approved_routes"] == [
        "Paxus",
    ]

    assert "Shiftr" not in approved["approved_routes"]
    assert "Thorio" not in approved["approved_routes"]


def test_thorio_approval_does_not_approve_shiftr_or_paxus():
    lead = {
        "company": "Thorio Only Corp",
        "fingerprint": "thorio-only-001",
        "potential_routes": [
            "Thorio",
            "Shiftr",
            "Paxus",
        ],
    }

    airtable_record = {
        "id": "rec_thorio_only_001",
        "fields": {
            "Review Status": "Approved to Contact",
            "Applicable Routes": [
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
            "rec_thorio_only_001",
        )

    approved = result["lead"]

    assert approved["approved_routes"] == [
        "Thorio",
    ]

    assert "Shiftr" not in approved["approved_routes"]
    assert "Paxus" not in approved["approved_routes"]


def test_all_three_routes_can_be_approved_together():
    lead = {
        "company": "All Routes Corp",
        "fingerprint": "all-routes-001",
        "potential_routes": [
            "Shiftr",
            "Paxus",
            "Thorio",
        ],
    }

    airtable_record = {
        "id": "rec_all_routes_001",
        "fields": {
            "Review Status": "Qualified",
            "Applicable Routes": [
                "Shiftr",
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
            "rec_all_routes_001",
        )

    approved = result["lead"]

    assert approved["approved_routes"] == [
        "Shiftr",
        "Paxus",
        "Thorio",
        ]
