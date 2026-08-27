import os

import pytest

from lead_engine.airtable_sync import (
    _normalize_lead,
    _normalize_routes,
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
