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

def test_commercial_strategy_exposes_buyer_intent_progression_history():
    from .sales_closer_intelligence import build_commercial_strategy

    lead = {
        "conversation_events": [
            {"outcome": "replied", "text": "We have a problem with engineering capacity.", "evidence_ref": "evt-problem"},
            {"outcome": "replied", "text": "It is causing release delays.", "evidence_ref": "evt-impact"},
            {"outcome": "replied", "text": "We are comparing providers.", "evidence_ref": "evt-eval"},
        ],
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "engineering capacity",
            "evidence_url": "https://example.com/need",
        },
    }
    strategy = build_commercial_strategy(lead)
    progression = strategy["buyer_intent_progression"]
    assert progression["current_state"] == "evaluation"
    assert len(progression["history"]) == 3
    assert progression["transition"]["evidence_ref"] == "evt-eval"
    assert strategy["conversation_intelligence"]["action_basis"] == "buyer_intent_progression"
    assert strategy["conversation_intelligence"]["next_best_action"] == "map_evaluation_process"


def test_confirmed_concern_remains_authoritative_over_progression():
    from .sales_closer_intelligence import build_commercial_strategy

    lead = {
        "outreach_state": "objection",
        "conversation_events": [
            {
                "outcome": "objection",
                "text": "We already have an internal engineering team.",
                "evidence_ref": "evt-objection",
            },
            {
                "outcome": "replied",
                "text": "Yes, avoiding disruption is the concern.",
                "underlying_concern_confirmation": "capability_or_displacement_risk",
                "evidence_ref": "evt-confirm",
            },
        ],
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "engineering capacity",
            "evidence_url": "https://example.com/need",
        },
    }
    strategy = build_commercial_strategy(
        lead,
        objection="We already have an internal engineering team.",
    )
    assert strategy["buyer_intent_progression"]["current_state"] == "existing_solution"
    assert strategy["conversation_intelligence"]["next_best_action"] == "de_risk_augmentation_fit"


def test_commercial_commitment_progression_selects_execution_question():
    from .sales_closer_intelligence import build_commercial_strategy

    lead = {
        "conversation_events": [
            {
                "outcome": "replied",
                "text": "Send the agreement and kickoff options.",
                "evidence_ref": "evt-commit",
            }
        ],
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "engineering capacity",
            "evidence_url": "https://example.com/need",
        },
    }
    strategy = build_commercial_strategy(lead)
    assert strategy["buyer_intent_progression"]["current_state"] == "commercial_commitment"
    assert strategy["conversation_intelligence"]["next_best_action"] == "confirm_commitment_details"
    assert "specific next step" in strategy["conversation_intelligence"]["next_best_question"].lower()
