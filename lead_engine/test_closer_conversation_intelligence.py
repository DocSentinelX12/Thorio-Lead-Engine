from .database import LeadDB
from .revenue_conversation import record_inbound_event


def test_objection_updates_persist_commercial_strategy(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = {
        "fingerprint": "closer-conversation-1",
        "company": "Acme",
        "outreach_route": "Shiftr",
        "outreach_state": "awaiting_response",
        "revenue_lifecycle_state": "outreach_sent",
        "conversation_id": "conversation:closer-conversation-1:shiftr",
    }
    db.insert_if_new(lead)

    record_inbound_event(
        db,
        opportunity_id=lead["fingerprint"],
        conversation_id=lead["conversation_id"],
        event_id="evt-objection-1",
        text="We already have an internal engineering team.",
        outcome="objection",
        objection="We already have an internal engineering team.",
    )

    stored = db.get(lead["fingerprint"])
    event = stored["conversation_events"][-1]
    assert stored["commercial_strategy"]["objection_category"] == "existing_solution"
    assert stored["commercial_strategy"]["next_best_action"] == "diagnose_capacity_gap"
    assert event["commercial_strategy"]["psychological_objective"] == "differentiate_without_attacking"
