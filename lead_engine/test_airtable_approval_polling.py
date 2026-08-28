from unittest.mock import patch

from lead_engine.airtable_approval_worker import (
    process_approval_batch,
)
from lead_engine.database import LeadDB


def test_approval_polling_processes_multiple_leads_independently(
    tmp_path,
):
    db = LeadDB(
        data_dir=str(tmp_path),
    )

    items = [
        {
            "record_id": "rec_poll_001",
            "lead": {
                "company": "Shiftr Corp",
                "fingerprint": "poll-001",
                "potential_routes": [
                    "Shiftr",
                    "Thorio",
                ],
            },
        },
        {
            "record_id": "rec_poll_002",
            "lead": {
                "company": "Paxus Corp",
                "fingerprint": "poll-002",
                "potential_routes": [
                    "Paxus",
                    "Thorio",
                ],
            },
        },
    ]

    def fake_fetch(record_id):
        records = {
            "rec_poll_001": {
                "id": "rec_poll_001",
                "fields": {
                    "Review Status": "Qualified",
                    "Applicable Routes": [
                        "Shiftr",
                    ],
                },
            },
            "rec_poll_002": {
                "id": "rec_poll_002",
                "fields": {
                    "Review Status": "Qualified",
                    "Applicable Routes": [
                        "Paxus",
                        "Thorio",
                    ],
                },
            },
        }

        return records[record_id]

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        side_effect=fake_fetch,
    ):
        result = process_approval_batch(
            db=db,
            items=items,
        )

    assert result["approved_count"] == 2
    assert result["pending_count"] == 0
    assert result["rejected_count"] == 0

    first = result["approved"][0]
    second = result["approved"][1]

    assert first["approved_routes"] == [
        "Shiftr",
    ]

    assert second["approved_routes"] == [
        "Paxus",
        "Thorio",
    ]

    assert first["lead"]["routes"] == [
        "Shiftr",
    ]

    assert second["lead"]["routes"] == [
        "Paxus",
        "Thorio",
    ]

    db.conn.close()


def test_approval_polling_does_not_reprocess_same_approval(
    tmp_path,
):
    db = LeadDB(
        data_dir=str(tmp_path),
    )

    item = {
        "record_id": "rec_poll_repeat_001",
        "lead": {
            "company": "Repeat Corp",
            "fingerprint": "poll-repeat-001",
            "potential_routes": [
                "Shiftr",
            ],
        },
    }

    record = {
        "id": "rec_poll_repeat_001",
        "fields": {
            "Review Status": "Qualified",
            "Applicable Routes": [
                "Shiftr",
            ],
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=record,
    ):
        first = process_approval_batch(
            db=db,
            items=[item],
        )

        second = process_approval_batch(
            db=db,
            items=[item],
        )

    assert first["approved_count"] == 1
    assert first["already_processed_count"] == 0

    assert second["approved_count"] == 0
    assert second["already_processed_count"] == 1

    db.conn.close()
