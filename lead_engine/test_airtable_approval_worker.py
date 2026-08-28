from unittest.mock import patch

from lead_engine.airtable_approval_worker import (
    process_airtable_approval,
    process_approval_batch,
)


def test_pending_lead_stays_out_of_delivery():
    lead = {
        "company": "Pending Worker Corp",
        "fingerprint": "worker-pending-001",
        "potential_routes": [
            "Shiftr",
            "Paxus",
        ],
    }

    record = {
        "id": "rec_pending_worker",
        "fields": {
            "Review Status": "Reviewing",
            "Applicable Routes": [
                "Shiftr",
                "Paxus",
            ],
        },
    }

    with patch(
        "lead_engine.airtable_approval_worker.read_approval",
        return_value={
            "status": "pending",
            "record": record,
            "lead": lead,
        },
    ):
        result = process_airtable_approval(
            db=None,
            lead=lead,
            record_id=record["id"],
        )

    assert result["status"] == "pending"
    assert result["delivered"] is False


def test_approved_lead_is_prepared_for_existing_delivery_system():
    lead = {
        "company": "Approved Worker Corp",
        "fingerprint": "worker-approved-001",
        "potential_routes": [
            "Shiftr",
            "Thorio",
        ],
    }

    with patch(
        "lead_engine.airtable_approval_worker.read_approval",
        return_value={
            "status": "approved",
            "record": {
                "id": "rec_approved_worker",
            },
            "lead": {
                **lead,
                "approved_routes": [
                    "Shiftr",
                    "Thorio",
                ],
            },
        },
    ):
        result = process_airtable_approval(
            db=None,
            lead=lead,
            record_id="rec_approved_worker",
        )

    assert result["status"] == "approved"
    assert result["delivered"] is False
    assert result["approved_routes"] == [
        "Shiftr",
        "Thorio",
    ]


def test_batch_keeps_route_decisions_separate():
    items = [
        {
            "record_id": "rec_1",
            "lead": {"company": "Approved"},
        },
        {
            "record_id": "rec_2",
            "lead": {"company": "Pending"},
        },
        {
            "record_id": "rec_3",
            "lead": {"company": "Rejected"},
        },
    ]

    responses = [
        {
            "status": "approved",
            "record": {"id": "rec_1"},
            "lead": {
                "company": "Approved",
                "approved_routes": ["Shiftr"],
            },
        },
        {
            "status": "pending",
            "record": {"id": "rec_2"},
            "lead": {"company": "Pending"},
        },
        {
            "status": "rejected",
            "record": {"id": "rec_3"},
            "lead": {"company": "Rejected"},
        },
    ]

    with patch(
        "lead_engine.airtable_approval_worker.read_approval",
        side_effect=responses,
    ):
        result = process_approval_batch(
            db=None,
            items=items,
        )

    assert result["approved_count"] == 1
    assert result["pending_count"] == 1
    assert result["rejected_count"] == 1

    assert result["approved"][0]["approved_routes"] == [
        "Shiftr",
          ]
