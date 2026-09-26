from lead_engine.database import LeadDB
from lead_engine.revenue_conversation import record_commercial_outcome


def test_final_human_handoff_exists_only_after_commercial_outcome(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new({"fingerprint": "sale-1", "company": "Acme"})
    assert db.get("sale-1").get("final_human_handoff") is None

    result = record_commercial_outcome(
        db,
        opportunity_id="sale-1",
        conversation_id="conversation-1",
        outcome="sale",
        details={"route": "Shiftr"},
    )

    assert result["outcome"] == "sale"
    stored = db.get("sale-1")
    assert stored["revenue_lifecycle_state"] == "closed_won"
    assert stored["final_human_handoff"]["ready"] is True
    assert stored["final_human_handoff"]["opportunity_id"] == "sale-1"


def test_noncommercial_outcome_cannot_create_final_human_handoff(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new({"fingerprint": "not-sale", "company": "Acme"})

    try:
        record_commercial_outcome(
            db,
            opportunity_id="not-sale",
            conversation_id="conversation-1",
            outcome="replied",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("noncommercial outcome unexpectedly created a final handoff")

    assert db.get("not-sale").get("final_human_handoff") is None
