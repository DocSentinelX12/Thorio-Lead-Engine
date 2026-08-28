from unittest.mock import patch

from lead_engine.airtable_approval_worker import (
    process_airtable_approval,
)


def test_approved_routes_remain_independent():
    db = __import__(
        "lead_engine.database",
        fromlist=["LeadDB"],
    ).LeadDB(
        data_dir="data/test_airtable_boundary"
    )

    lead = {
        "company": "Boundary Corp",
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
                "Thorio",
            ],
        },
    }

    with patch(
        "lead_engine.airtable_approval.fetch_record",
        return_value=airtable_record,
    ):
        result = process_airtable_approval(
            db=db,
            lead=lead,
            record_id="rec_boundary_001",
        )

    assert result["status"] == "approved"
    assert result["approved_routes"] == [
        "Shiftr",
        "Thorio",
    ]

    assert "Paxus" not in result["approved_routes"]
    assert result["lead"]["routes"] == [
        "Shiftr",
        "Thorio",
    ]

    assert result["lead"]["potential_routes"] == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]

    db.conn.close()
