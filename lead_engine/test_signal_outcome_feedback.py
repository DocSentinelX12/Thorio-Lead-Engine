from .database import LeadDB
from .signal_outcome_feedback import (
    build_signal_outcome_feedback,
    persist_signal_outcome_feedback,
    signal_feedback_priority,
)
from .unified_opportunity_signal_graph import build_unified_opportunity_signal_graph


def _lead(fingerprint, outcome):
    return {
        "fingerprint": fingerprint,
        "opportunity_id": fingerprint,
        "company": "Acme",
        "source": "LinkedIn",
        "source_id": fingerprint,
        "url": f"https://example.com/{fingerprint}",
        "signal": "Acme is looking for a development partner.",
        "evidence": "We are looking for a development partner.",
        "signal_type": "commercial_intent",
        "signal_matches": ["looking for a development partner"],
        "discovered_at": "2026-09-29T12:00:00+00:00",
        "outreach_history": [{"action_id": f"action-{fingerprint}", "status": "sent"}],
        "conversation_events": [{"event_id": f"event-{fingerprint}", "outcome": outcome, "at": "2026-09-29T13:00:00+00:00"}],
        "revenue_lifecycle_state": "converted" if outcome == "converted" else "conversation_active",
    }


def test_feedback_is_derived_from_graph_and_remains_association_only():
    graph = build_unified_opportunity_signal_graph([_lead("a", "converted"), _lead("b", "no_response")])
    feedback = build_signal_outcome_feedback(graph)
    item = feedback["by_signal"]["configured|looking for a development partner"]
    assert item["distinct_opportunities"] == 2
    assert item["outcomes"]["converted"] == 1
    assert item["outcomes"]["no_response"] == 1
    assert item["association_only"] is True
    assert "caused" in item["feedback_rule"] or "causal" in item["feedback_rule"]


def test_feedback_persists_and_drives_future_research_priority(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead("a", "converted"))
    feedback = persist_signal_outcome_feedback(db)
    assert feedback["by_signal"]["configured|looking for a development partner"]["research_priority"] == 2
    assert signal_feedback_priority(db.get("a"), feedback) == 2
    assert db.get_state("unified_opportunity_signal_graph")["authoritative"] is True
    assert db.get_state("signal_outcome_feedback")["association_only"] is True
