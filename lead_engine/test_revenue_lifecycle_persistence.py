from .database import LeadDB


def test_revenue_lifecycle_cannot_regress_from_conversation_to_older_stage(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = {
        "fingerprint": "lifecycle-monotonic-test",
        "company": "Acme",
        "qualified": True,
        "sales_eligibility": "eligible",
        "revenue_lifecycle_state": "conversation_active",
        "conversation_id": "conversation:lifecycle-monotonic-test:thorio",
        "outreach_state": "awaiting_response",
        "outreach_attempt": 2,
        "last_outreach_action_id": "action-2",
        "next_follow_up_at": "2030-01-01T00:00:00+00:00",
        "follow_up_due": True,
        "outreach_history": [{"action_id": "action-1"}, {"action_id": "action-2"}],
    }
    db.insert_if_new(lead)
    updated = db.update_payload(lead["fingerprint"], {
        "revenue_lifecycle_state": "outreach_sent",
        "sales_eligibility": "eligible",
        "outreach_state": "awaiting_response",
        "outreach_attempt": 1,
        "last_outreach_action_id": "stale-action",
        "conversation_id": "stale-conversation",
    })
    assert updated["revenue_lifecycle_state"] == "conversation_active"
    assert updated["outreach_attempt"] == 2
    assert updated["last_outreach_action_id"] == "action-2"
    assert updated["conversation_id"] == lead["conversation_id"]
    assert updated["outreach_history"] == lead["outreach_history"]


def test_revenue_fields_cannot_regress_from_qualified_same_stage_stale_snapshot(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = {
        "fingerprint": "lifecycle-equal-stage-stale-test",
        "company": "Acme",
        "qualified": True,
        "sales_eligibility": "blocked",
        "sales_eligibility_reason": "airtable_handoff_required",
        "revenue_lifecycle_state": "qualified",
        "eligible_routes": ["Thorio"],
        "preserved_routes": ["Thorio"],
    }
    db.insert_if_new(lead)
    stale_snapshot = {
        "fingerprint": lead["fingerprint"],
        "qualified": True,
        "sales_eligibility": None,
        "sales_eligibility_reason": None,
        "revenue_lifecycle_state": "qualified",
        "eligible_routes": [],
        "preserved_routes": [],
    }
    updated = db.update_payload(lead["fingerprint"], stale_snapshot)
    assert updated["sales_eligibility"] == "blocked"
    assert updated["sales_eligibility_reason"] == "airtable_handoff_required"
    assert updated["eligible_routes"] == ["Thorio"]
    assert updated["preserved_routes"] == ["Thorio"]
    assert updated["revenue_lifecycle_state"] == "qualified"
    db.close()


def test_terminal_revenue_lifecycle_state_cannot_change_to_another_terminal_state(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    for terminal_state, attempted_state in (("converted", "closed_lost"), ("referred", "converted"), ("closed_lost", "stopped"), ("disqualified", "converted"), ("stopped", "referred")):
        fingerprint = f"terminal-{terminal_state}-{attempted_state}"
        lead = {
            "fingerprint": fingerprint,
            "company": "Acme",
            "revenue_lifecycle_state": terminal_state,
            "outreach_state": terminal_state,
        }
        assert db.insert_if_new(lead) is True
        updated = db.update_payload(fingerprint, {
            "revenue_lifecycle_state": attempted_state,
            "outreach_state": attempted_state,
        })
        assert updated["revenue_lifecycle_state"] == terminal_state
        assert updated["outreach_state"] == terminal_state
        assert db.get(fingerprint)["revenue_lifecycle_state"] == terminal_state
        assert db.get(fingerprint)["outreach_state"] == terminal_state
    db.close()
