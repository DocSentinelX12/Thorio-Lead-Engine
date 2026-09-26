import json
from unittest.mock import patch

from .database import LeadDB
from .pipeline import LeadPipeline
from .sync_worker import sync_pending


def test_failed_sync_stays_local_and_can_retry(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    pipeline = LeadPipeline(db=db)

    with patch(
        "lead_engine.pipeline.sync_one"
    ) as mock_sync:
        mock_sync.return_value = {
            "status": "failed",
            "lead": {},
            "airtable_record": None,
            "research_record": None,
            "outreach_record": None,
            "followup_record": None,
            "referral_record": None,
            "master_tracker": None,
            "error": "Airtable unavailable",
        }

        result = pipeline.process(
            source="test",
            source_id="reliability-001",
            url="https://example.com/jobs/reliability-001",
            company="Reliability Corp",
            signal="remote software engineer",
            evidence="Remote software engineer opening found.",
        )

    assert result["accepted"] is True
    assert result["sync_status"] == "failed"

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync, patch(
        "lead_engine.sync_worker.sync_research"
    ) as mock_research, patch(
        "lead_engine.sync_worker.sync_outreach"
    ) as mock_outreach, patch(
        "lead_engine.sync_worker.sync_followup"
    ) as mock_followup, patch(
        "lead_engine.sync_worker.sync_master_tracker"
    ) as mock_master_tracker, patch(
        "lead_engine.sync_worker.package_is_ready",
        return_value=True,
    ):

        mock_sync.return_value = {
            "status": "created",
            "record": {
                "id": "rec_retry_001"
            },
        }

        mock_research.return_value = {
            "status": "created",
            "record": {
                "id": "research_retry_001"
            },
        }

        mock_outreach.return_value = {
            "status": "created",
            "record": {
                "id": "outreach_retry_001"
            },
        }

        mock_followup.return_value = {
            "status": "created",
            "record": {
                "id": "followup_retry_001"
            },
        }

        mock_master_tracker.return_value = {
            "status": "synced",
        }

        retry_result = sync_pending(db)

    assert retry_result["synced_count"] == 1
    assert retry_result["failed_count"] == 0

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 1
    assert stats[2] == 0


def test_sync_pending_rejects_non_object_payload(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    fingerprint = "invalid-payload-001"

    db.conn.execute(
        """
        INSERT INTO leads
        (fingerprint, payload, synced, attempts)
        VALUES (?, ?, 0, 0)
        """,
        (
            fingerprint,
            json.dumps(
                [
                    "not",
                    "a",
                    "lead",
                ]
            ),
        ),
    )

    db.conn.commit()

    with patch(
        "lead_engine.sync_worker.sync_lead_if_missing"
    ) as mock_sync:
        result = sync_pending(db)

    mock_sync.assert_not_called()

    assert result["synced_count"] == 0
    assert result["already_exists_count"] == 0
    assert result["failed_count"] == 1

    assert (
        result["failed"][0]["error"]
        == "Invalid stored lead payload: expected an object."
    )

    stats = db.stats()

    assert stats[0] == 1
    assert stats[1] == 0
    assert stats[2] == 1


def test_autonomous_revenue_eligibility_syncs_outreach_without_human_delivery_approval(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    lead = {
        "fingerprint": "autonomous-outreach-airtable-001",
        "company": "Acme Corp",
        "qualified": True,
        "sales_eligibility": "eligible",
        "delivery_status": "pending",
        "route": "",
        "outreach_route": "Shiftr",
        "active_route": "Shiftr",
        "contact_email": "jane@example.com",
        "outreach_state": "awaiting_response",
        "outreach_attempt": 1,
        "last_outreach_action_id": "action-001",
        "last_outreach_delivery": {"transport": "fake", "thread_url": "https://example.com/thread/1", "confirmed_at": "2026-09-19T00:00:00+00:00"},
        "conversation_id": "conversation:autonomous-outreach-airtable-001:shiftr",
        "next_follow_up_at": "2026-09-22T12:00:00+00:00",
        "last_response_outcome": "",
        "potential_routes": ["Shiftr"],
        "eligible_routes": ["Shiftr"],
        "preserved_routes": ["Shiftr"],
        "research_status": "complete",
        "research_verified_fields": ["current_intent_research", "route_research"],
        "company_research": {"company_verified": True, "decision_maker": "Jane", "decision_maker_verification_status": "verified"},
        "current_intent_research": {"verified": True, "verification_status": "verified"},
        "route_research": {"verified": True, "verification_status": "verified"},
        "qualification_results": {"Shiftr": {"qualified": True, "route_research": {"verified": True}}},
    }

    with patch("lead_engine.sync_worker.sync_lead_if_missing", return_value={"status": "created", "record": {"id": "lead-001"}}), \
         patch("lead_engine.sync_worker.package_is_ready", return_value=True), \
         patch("lead_engine.sync_worker.package_digest", return_value="test-digest"), \
         patch("lead_engine.sync_worker.verify_airtable_handoff", return_value=(True, "test-digest")), \
         patch("lead_engine.sync_worker.sync_research", return_value={"status": "created", "record": {"id": "research-001"}}), \
         patch("lead_engine.sync_worker.sync_outreach", return_value={"status": "created", "record": {"id": "outreach-001"}}) as mock_outreach, \
         patch("lead_engine.sync_worker.sync_master_tracker", return_value={"status": "synced"}) as mock_master:
        from .sync_worker import sync_one
        result = sync_one(lead, db=db)

    assert result["status"] == "synced"
    mock_outreach.assert_called_once()
    outreach_payload = mock_outreach.call_args.args[0]
    assert outreach_payload["route"] == "Shiftr"
    assert outreach_payload["outreach_status"] == "Contacted"
    assert outreach_payload["next_action_date"] == "2026-09-22T12:00:00+00:00"
    assert outreach_payload["date_sent"] == "2026-09-19T00:00:00+00:00"
    mock_master.assert_called_once()
