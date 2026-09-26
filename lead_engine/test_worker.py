import pytest
from unittest.mock import patch

from .database import LeadDB
from .sync_worker import (
    sync_one,
    sync_pending,
)
from .sales_handoff import package_digest
from .research_intelligence import build_research_intelligence
import json


@pytest.fixture(autouse=True)
def mock_research_sync(monkeypatch):
    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_research",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_research_test",
            },
        },
    )


def test_sync_worker_retries_failed_lead(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "lead_engine.sync_worker.package_is_ready",
        lambda lead: True,
    )

    db = LeadDB(
        data_dir=str(tmp_path)
    )

    lead = {
        "source": "test",
        "source_id": "worker-001",
        "url": "https://example.com/jobs/worker-001",
        "company": "Worker Corp",
        "signal": "remote developer",
        "evidence": "Remote developer opening found.",
        "route": "Shiftr",
        "potential_routes": [
            "Shiftr",
            "Thorio",
        ],
        "status": "Unverified",
        "fingerprint": "worker-fingerprint-001",
    }

    db.insert_if_new(lead)

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync:
        mock_sync.side_effect = Exception(
            "Airtable temporarily unavailable"
        )

        first_result = sync_pending(db)

    assert first_result["synced_count"] == 0
    assert first_result["failed_count"] == 1

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync, patch(
        "lead_engine.sync_worker.sync_outreach"
    ) as mock_outreach, patch(
        "lead_engine.sync_worker.sync_followup"
    ) as mock_followup, patch(
        "lead_engine.sync_worker.sync_master_tracker"
    ) as mock_master_tracker, patch(
        "lead_engine.sync_worker.package_digest",
        return_value="test-digest",
    ), patch(
        "lead_engine.sync_worker.verify_airtable_handoff",
        return_value=(True, "test-digest"),
    ):

        mock_sync.return_value = {
            "status": "created",
            "record": {
                "id": "rec_worker_001"
            },
        }

        mock_outreach.return_value = {
            "status": "created",
            "record": {
                "id": "outreach_001"
            },
        }

        mock_followup.return_value = {
            "status": "created",
            "record": {
                "id": "followup_001"
            },
        }

        mock_master_tracker.return_value = {
            "status": "synced",
        }

        second_result = sync_pending(db)

    assert second_result["synced_count"] == 1
    assert second_result["failed_count"] == 0

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0


def test_sync_one_requires_successful_lead_radar_record(
    monkeypatch,
):
    lead = {
        "fingerprint": "lead-001",
        "company": "Example Corp",
        "route": "Thorio",
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": None,
        },
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "failed"

    assert (
        result["error"]
        == (
            "Lead Radar synchronization succeeded without "
            "returning an Airtable record."
        )
    )


def test_sync_one_defers_incomplete_research_projection_after_lead_radar(
    monkeypatch,
):
    lead = {
        "fingerprint": "lead-research-required",
        "company": "Example Corp",
        "route": "Thorio",
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_lead_research",
            },
        },
    )

    research_calls = []

    def research_sync(lead_payload):
        research_calls.append(lead_payload)
        return {
            "status": "created",
            "record": {
                "id": "rec_research_required",
            },
        }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_research",
        research_sync,
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "deferred_research"
    assert result["research_record"] is None
    assert result["airtable_record"]["id"] == "rec_lead_research"
    assert result["reason"] == "research_verification_pending"
    assert research_calls == []


def test_sync_one_fails_and_remains_retryable_when_research_sync_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        "lead_engine.sync_worker.package_is_ready",
        lambda lead: True,
    )

    lead = {
        "fingerprint": "lead-research-failure",
        "company": "Example Corp",
        "route": "Thorio",
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_lead_research_failure",
            },
        },
    )

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_research",
        lambda lead: {
            "status": "failed",
            "error": "research Airtable failure",
        },
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "failed"
    assert result["research_record"] is None
    assert result["error"] == "research Airtable failure"


def test_sync_one_requires_valid_master_tracker_result(
    monkeypatch,
):
    monkeypatch.setattr(
        "lead_engine.sync_worker.package_is_ready",
        lambda lead: True,
    )

    lead = {
        "fingerprint": "lead-002",
        "company": "Example Corp",
        "route": "Thorio",
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_lead_002",
            },
        },
    )

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_master_tracker",
        lambda lead: {
            "status": "failed",
            "error": "downstream failure",
        },
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "failed"

    assert (
        result["error"]
        == "downstream failure"
    )


def test_sync_one_fails_when_outreach_sync_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        "lead_engine.sync_worker.package_is_ready",
        lambda lead: True,
    )

    lead = {
        "fingerprint": "lead-outreach-failure",
        "company": "Example Corp",
        "route": "Paxus",
        "delivery_status": "approved",
        "contact_email": "test@example.com",
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_lead_003",
            },
        },
    )

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_outreach",
        lambda outreach: {
            "status": "failed",
            "error": "outreach failure",
        },
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "failed"
    assert result["error"] == "outreach failure"


def test_sync_one_fails_when_followup_sync_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        "lead_engine.sync_worker.package_is_ready",
        lambda lead: True,
    )

    lead = {
        "fingerprint": "lead-followup-failure",
        "company": "Example Corp",
        "route": "Paxus",
        "delivery_status": "approved",
        "contact_email": "test@example.com",
        "next_action_date": "2026-09-10",
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_lead_004",
            },
        },
    )

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_outreach",
        lambda outreach: {
            "status": "created",
            "record": {
                "id": "rec_outreach_004",
            },
        },
    )

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_followup",
        lambda followup: {
            "status": "failed",
            "error": "followup failure",
        },
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "failed"
    assert result["error"] == "followup failure"


def test_sync_one_fails_when_referral_sync_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        "lead_engine.sync_worker.package_is_ready",
        lambda lead: True,
    )

    lead = {
        "fingerprint": "lead-referral-failure",
        "company": "Example Corp",
        "route": "Paxus",
        "referral_submitted": True,
    }

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_lead_if_missing",
        lambda lead: {
            "status": "created",
            "record": {
                "id": "rec_lead_005",
            },
        },
    )

    monkeypatch.setattr(
        "lead_engine.sync_worker.sync_paxus_referral_state",
        lambda referral: {
            "status": "failed",
            "error": "referral failure",
        },
    )

    result = sync_one(
        lead
    )

    assert result["status"] == "failed"
    assert result["error"] == "referral failure"


def test_sync_one_records_exact_handoff_for_sales_ready_package(tmp_path, monkeypatch):
    db = LeadDB(data_dir=str(tmp_path))
    lead = {
        "fingerprint": "worker-handoff-ready",
        "opportunity_id": "worker-handoff-ready",
        "company": "Acme",
        "contact_email": "taylor@example.com",
        "qualified": True,
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "taylor@example.com",
        },
        "decision_maker_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/taylor", "evidence": "Taylor is the decision maker.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "engineering expansion", "evidence": [{"url": "https://example.com/need", "evidence": "Acme needs engineering expansion.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "engineering expansion", "evidence": [{"url": "https://example.com/intent", "evidence": "Acme has current engineering intent.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Acme is hiring engineers.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Commercial context.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Engineering expansion is relevant to Thorio.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Acme needs engineering expansion.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "potential_routes": ["Thorio"], "eligible_routes": ["Thorio"], "preserved_routes": ["Thorio"], "routing_result": {"destinations": ["Thorio"], "review_required": False},
    }
    lead["research_intelligence"] = build_research_intelligence(lead)
    db.insert_if_new(lead)
    digest = package_digest(lead)
    raw = dict(lead)
    raw["__thorio_package_digest"] = digest

    monkeypatch.setattr("lead_engine.sync_worker.sync_lead_if_missing", lambda payload: {"status": "created", "record": {"id": "recLead", "fields": {"Duplicate Key": payload["fingerprint"], "Company": payload["company"]}}})
    monkeypatch.setattr("lead_engine.sync_worker.sync_research", lambda payload: {"status": "created", "record": {"id": "recResearch", "fields": {"Research Key": payload["fingerprint"], "Lead Fingerprint": payload["fingerprint"], "Raw Research Package": json.dumps(raw, sort_keys=True)}}})
    monkeypatch.setattr("lead_engine.sync_worker.sync_master_tracker", lambda payload: {"status": "synced", "company": {"status": "created", "record": {"id": "recCompany", "fields": {"Company": payload["company"]}}}, "opportunities": []})

    result = sync_one(lead, db=db)

    assert result["status"] == "synced"
    assert result["package_digest"] == digest
    assert db.get_airtable_handoff(lead["fingerprint"])["package_digest"] == digest
