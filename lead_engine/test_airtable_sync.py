import os

import pytest

from lead_engine.airtable_sync import (
    _normalize_lead,
    _normalize_routes,
    sync_lead_if_missing,
)


def test_normalize_routes_supports_all_three_routes():
    routes = _normalize_routes(
        ["Paxus", "Shiftr", "Thorio"]
    )

    assert routes == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]


def test_normalize_routes_rejects_unknown_routes():
    routes = _normalize_routes(
        ["Paxus", "Unknown", "Thorio"]
    )

    assert routes == [
        "Paxus",
        "Thorio",
    ]


def test_normalize_lead_maps_core_airtable_fields():
    lead = {
        "company": "Example Corp",
        "source": "linkedin",
        "url": "https://example.com/job",
        "signal": "Remote software engineer",
        "evidence": "Company is hiring a remote software engineer.",
        "person": "Jane Smith",
        "contact_title": "CTO",
        "fingerprint": "example-fingerprint",
        "lead_score": 92,
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
        "qualified": True,
        "evidence_status": "Verified",
    }

    fields = _normalize_lead(lead)

    assert fields["Company"] == "Example Corp"
    assert fields["Source Platform"] == "LinkedIn"
    assert fields["Signal"] == "Remote software engineer"
    assert fields["Decision Maker"] == "Jane Smith"
    assert fields["Title"] == "CTO"
    assert fields["Duplicate Key"] == "example-fingerprint"
    assert fields["Lead Score"] == 92
    assert fields["Qualified Lead?"] is True
    assert fields["Evidence Status"] == "Verified"
    assert fields["Applicable Routes"] == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]


def test_normalize_lead_preserves_independent_routes():
    lead = {
        "company": "Multi Route Corp",
        "source": "company website",
        "signal": "AI automation need",
        "evidence": "Company announced an AI automation project.",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    fields = _normalize_lead(lead)

    assert fields["Applicable Routes"] == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]

    assert fields["Recommended Partner"] == "Both"


def test_airtable_configuration_uses_expected_environment_names():
    assert "AIRTABLE_API_KEY" in {
        "AIRTABLE_API_KEY",
        "AIRTABLE_BASE_ID",
        "AIRTABLE_LEAD_TABLE",
    }

    assert "AIRTABLE_BASE_ID" in {
        "AIRTABLE_API_KEY",
        "AIRTABLE_BASE_ID",
        "AIRTABLE_LEAD_TABLE",
    }

    assert "AIRTABLE_LEAD_TABLE" in {
        "AIRTABLE_API_KEY",
        "AIRTABLE_BASE_ID",
        "AIRTABLE_LEAD_TABLE",
  }


def test_sync_lead_if_missing_updates_existing_record_without_overwriting_human_fields():
    lead = {
        "company": "Existing Corp",
        "source": "linkedin",
        "source_id": "existing-001",
        "url": "https://example.com/company",
        "signal": "Hiring software engineers",
        "evidence": "Company is actively hiring software engineers.",
        "fingerprint": "existing-fingerprint",
        "lead_score": 91,
        "priority": "Hot",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    existing_record = {
        "id": "rec_existing_001",
        "fields": {
            "Duplicate Key": "existing-fingerprint",
            "Review Status": "Qualified",
            "Qualified Lead?": True,
            "Contact Ready": True,
            "Outreach Status": "Contacted",
            "Notes": "Human note must survive synchronization.",
        },
    }

    captured = {}

    def fake_find(
        fingerprint,
    ):
        assert fingerprint == "existing-fingerprint"
        return [existing_record]

    def fake_update(
        table_key,
        record_id,
        fields,
    ):
        captured["table_key"] = table_key
        captured["record_id"] = record_id
        captured["fields"] = fields

        return {
            "records": [
                {
                    "id": record_id,
                    "fields": {
                        **existing_record["fields"],
                        **fields,
                    },
                }
            ]
        }

    from unittest.mock import patch

    with patch(
        "lead_engine.airtable_sync.find_by_fingerprint",
        side_effect=fake_find,
    ), patch(
        "lead_engine.airtable_sync.update_master_record",
        side_effect=fake_update,
    ), patch(
        "lead_engine.airtable_sync.create_master_record"
    ) as mock_create:

        result = sync_lead_if_missing(
            lead
        )

    assert result["status"] == "updated"

    assert captured["table_key"] == "lead_radar"
    assert captured["record_id"] == "rec_existing_001"

    assert captured["fields"]["Company"] == "Existing Corp"
    assert captured["fields"]["Signal"] == "Hiring software engineers"
    assert captured["fields"]["Duplicate Key"] == "existing-fingerprint"
    assert captured["fields"]["Lead Score"] == 91
    assert captured["fields"]["Priority"] == "Hot"
    assert captured["fields"]["Applicable Routes"] == [
        "Paxus",
        "Shiftr",
        "Thorio",
    ]

    assert "Review Status" not in captured["fields"]
    assert "Qualified Lead?" not in captured["fields"]
    assert "Contact Ready" not in captured["fields"]
    assert "Outreach Status" not in captured["fields"]
    assert "Notes" not in captured["fields"]

    mock_create.assert_not_called()

def test_sync_opportunities_creates_one_opportunity_per_non_thorio_route(
    monkeypatch,
):
    created = []

    def fake_find_master_records(
        table_key,
        lookup_field,
        lookup_value,
    ):
        return []

    def fake_create_master_record(
        table_key,
        fields,
    ):
        created.append(
            {
                "table_key": table_key,
                "fields": fields,
            }
        )

        return {
            "records": [
                {
                    "id": f"rec{len(created)}",
                    "fields": fields,
                }
            ]
        }

    monkeypatch.setattr(
        "lead_engine.master_tracker_sync.find_master_records",
        fake_find_master_records,
    )

    monkeypatch.setattr(
        "lead_engine.master_tracker_sync.create_master_record",
        fake_create_master_record,
    )

    lead = {
        "qualified": True,
        "fingerprint": "fingerprint",
        "company": "Example Company",
        "signal": "software engineering hiring",
        "signal_type": "hiring",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    from lead_engine.master_tracker_sync import sync_opportunities

    results = sync_opportunities(lead)

    assert len(results) == 2
    assert len(created) == 2

    assert all(
        item["table_key"] == "opportunities"
        for item in created
    )

    opportunity_values = {
        item["fields"]["Opportunity"]
        for item in created
    }

    assert opportunity_values == {
        "fingerprint:Paxus",
        "fingerprint:Shiftr",
    }


def test_sync_opportunities_excludes_thorio_only_route(
    monkeypatch,
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "Thorio must not create an Opportunity."
        )

    monkeypatch.setattr(
        "lead_engine.master_tracker_sync.find_master_records",
        fail_if_called,
    )

    lead = {
        "qualified": True,
        "fingerprint": "fingerprint",
        "company": "Example Company",
        "potential_routes": [
            "Thorio",
        ],
    }

    from lead_engine.master_tracker_sync import sync_opportunities

    results = sync_opportunities(lead)

    assert results == []


def test_sync_opportunities_is_idempotent_by_route(
    monkeypatch,
):
    records = {
        "fingerprint:Paxus": {
            "id": "rec_paxus",
            "fields": {
                "Opportunity": "fingerprint:Paxus",
            },
        },
        "fingerprint:Shiftr": {
            "id": "rec_shiftr",
            "fields": {
                "Opportunity": "fingerprint:Shiftr",
            },
        },
    }

    updated = []

    def fake_find_master_records(
        table_key,
        lookup_field,
        lookup_value,
    ):
        record = records.get(lookup_value)

        if record is None:
            return []

        return [record]

    def fake_update_master_record(
        table_key,
        record_id,
        fields,
    ):
        updated.append(
            {
                "table_key": table_key,
                "record_id": record_id,
                "fields": fields,
            }
        )

        return {
            "records": [
                {
                    "id": record_id,
                    "fields": fields,
                }
            ]
        }

    monkeypatch.setattr(
        "lead_engine.master_tracker_sync.find_master_records",
        fake_find_master_records,
    )

    monkeypatch.setattr(
        "lead_engine.master_tracker_sync.update_master_record",
        fake_update_master_record,
    )

    lead = {
        "qualified": True,
        "fingerprint": "fingerprint",
        "company": "Example Company",
        "signal": "software engineering hiring",
        "signal_type": "hiring",
        "potential_routes": [
            "Paxus",
            "Shiftr",
            "Thorio",
        ],
    }

    from lead_engine.master_tracker_sync import sync_opportunities

    results = sync_opportunities(lead)

    assert len(results) == 2
    assert len(updated) == 2

    updated_ids = {
        item["record_id"]
        for item in updated
    }

    assert updated_ids == {
        "rec_paxus",
        "rec_shiftr",
    }


def test_sync_outreach_uses_actual_airtable_schema(
    monkeypatch,
):
    captured = {}

    def fake_find_master_records(
        table_key,
        lookup_field,
        lookup_value,
    ):
        assert table_key == "outreach"
        assert lookup_field == "Outreach"
        assert (
            lookup_value
            == "fingerprint-001:Paxus"
        )
        return []

    def fake_create_master_record(
        table_key,
        fields,
    ):
        captured["table_key"] = table_key
        captured["fields"] = fields

        return {
            "records": [
                {
                    "id": "rec_outreach_001",
                    "fields": fields,
                }
            ]
        }

    monkeypatch.setattr(
        "lead_engine.airtable_sync.find_master_records",
        fake_find_master_records,
    )

    monkeypatch.setattr(
        "lead_engine.airtable_sync.create_master_record",
        fake_create_master_record,
    )

    from lead_engine.airtable_sync import sync_outreach

    result = sync_outreach(
        {
            "fingerprint": "fingerprint-001",
            "company": "Example Corp",
            "route": "Paxus",
            "platform": "Himalayas",
            "follow_up_number": 0,
            "response": "",
            "next_action_date": "2026-09-10",
        }
    )

    assert result["status"] == "created"

    fields = captured["fields"]

    assert fields["Outreach"] == (
        "fingerprint-001:Paxus"
    )

    assert fields["Company"] == "Example Corp"

    assert fields["Opportunity"] == (
        "fingerprint-001:Paxus"
    )

    assert fields["Platform"] == "Other"

    assert fields["Follow-up Number"] == 0

    assert fields["Next Follow-up"] == (
        "2026-09-10"
    )

    assert "Lead" not in fields
    assert "Route" not in fields
    assert "Outreach Status" not in fields
    assert "Next Action Date" not in fields
    assert "Date Sent" not in fields


def test_sync_followup_uses_actual_airtable_schema(
    monkeypatch,
):
    captured = {}

    def fake_find_master_records(
        table_key,
        lookup_field,
        lookup_value,
    ):
        assert table_key == "followups"
        assert lookup_field == "Follow-up"
        assert (
            lookup_value
            == "fingerprint-002:Shiftr:1"
        )
        return []

    def fake_create_master_record(
        table_key,
        fields,
    ):
        captured["table_key"] = table_key
        captured["fields"] = fields

        return {
            "records": [
                {
                    "id": "rec_followup_001",
                    "fields": fields,
                }
            ]
        }

    monkeypatch.setattr(
        "lead_engine.airtable_sync.find_master_records",
        fake_find_master_records,
    )

    monkeypatch.setattr(
        "lead_engine.airtable_sync.create_master_record",
        fake_create_master_record,
    )

    from lead_engine.airtable_sync import sync_followup

    result = sync_followup(
        {
            "fingerprint": "fingerprint-002",
            "company": "Example Corp",
            "route": "Shiftr",
            "due_date": "2026-09-12",
            "status": "pending",
            "follow_up_number": 1,
            "notes": "Verify project budget.",
        }
    )

    assert result["status"] == "created"

    fields = captured["fields"]

    assert fields["Follow-up"] == (
        "fingerprint-002:Shiftr:1"
    )

    assert fields["Company"] == "Example Corp"

    assert fields["Opportunity"] == (
        "fingerprint-002:Shiftr"
    )

    assert fields["Due Date"] == (
        "2026-09-12"
    )

    assert fields["Type"] == "Follow-up #1"

    assert fields["Status"] == "Open"

    assert fields["Notes"] == (
        "Verify project budget."
    )

    assert "Lead" not in fields
    assert "Route" not in fields
    assert "Follow-up Number" not in fields
