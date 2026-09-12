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
