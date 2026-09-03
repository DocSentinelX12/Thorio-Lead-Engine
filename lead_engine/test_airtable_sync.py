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
