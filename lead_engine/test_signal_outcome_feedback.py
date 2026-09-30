from .database import LeadDB
from .lead_identity import canonical_opportunity_identity
from .signal_outcome_feedback import (
    build_signal_outcome_feedback,
    persist_signal_outcome_feedback,
    signal_feedback_priority,
)
from .unified_opportunity_signal_graph import build_unified_opportunity_signal_graph


def _lead(fingerprint, outcome, *, signal_observed_at="2026-09-29T12:00:00+00:00", outcome_at="2026-09-29T13:00:00+00:00"):
    base = {
        "company": "Acme",
        "source": "LinkedIn",
        "source_id": fingerprint,
        "url": f"https://example.com/{fingerprint}",
        "signal": "Acme is looking for a development partner.",
        "evidence": "We are looking for a development partner.",
        "signal_type": "commercial_intent",
        "signal_matches": ["looking for a development partner"],
        "discovered_at": signal_observed_at,
    }
    identity = canonical_opportunity_identity(base)
    return {
        **base,
        "fingerprint": identity["fingerprint"],
        "opportunity_id": identity["opportunity_id"],
        "identity_version": identity["identity_version"],
        "identity_derivation": identity["identity_derivation"],
        "company": "Acme",
        "source": "LinkedIn",
        "source_id": fingerprint,
        "url": f"https://example.com/{fingerprint}",
        "signal": "Acme is looking for a development partner.",
        "evidence": "We are looking for a development partner.",
        "signal_type": "commercial_intent",
        "signal_matches": ["looking for a development partner"],
        "outreach_history": [{"action_id": f"action-{fingerprint}", "status": "sent"}],
        "conversation_events": [{"event_id": f"event-{fingerprint}", "outcome": outcome, "at": outcome_at}],
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


def test_feedback_priority_is_applied_to_future_research_targets():
    from .next_evidence_intelligence import build_next_evidence_plan

    feedback = {
        "by_signal": {
            "configured|looking for a development partner": {
                "research_priority": 2,
            }
        }
    }
    lead = _lead("future", "converted")
    plan = build_next_evidence_plan(lead, feedback=feedback)
    assert plan["feedback_applied"] is True
    assert all(target["priority"] == 3 for target in plan["targets"])
    assert all(target["feedback"]["association_only"] is True for target in plan["targets"])


def test_feedback_reaches_future_discovery_priority(tmp_path):
    from .agent_orchestrator import AgentOrchestrator
    from .agent_queue import pending

    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead("prior", "converted"))
    persist_signal_outcome_feedback(db)
    record = {
        "source": "LinkedIn",
        "source_id": "new-signal",
        "url": "https://example.com/new-signal",
        "signal": "Looking for a development partner.",
        "evidence": "Looking for a development partner.",
        "signal_matches": ["looking for a development partner"],
    }
    task = AgentOrchestrator(db).dispatch_discovery("linkedin_signal", record, priority=4)
    assert task["priority"] == 6
    queued = pending(db)
    assert any(item["task_id"] == task["task_id"] and item["priority"] == 6 for item in queued)


def test_feedback_does_not_learn_from_signal_observed_after_outcome():
    graph = build_unified_opportunity_signal_graph([
        _lead("later", "converted", signal_observed_at="2026-09-29T14:00:00+00:00", outcome_at="2026-09-29T13:00:00+00:00")
    ])
    feedback = build_signal_outcome_feedback(graph)
    assert feedback["by_signal"] == {}


def test_feedback_keeps_distinct_explicit_outcomes_but_deduplicates_same_event():
    lead = _lead("dup", "interested")
    lead["conversation_events"].append(dict(lead["conversation_events"][0]))
    graph = build_unified_opportunity_signal_graph([lead])
    feedback = build_signal_outcome_feedback(graph)
    item = feedback["by_signal"]["configured|looking for a development partner"]
    assert item["observations"] == 1
    assert item["outcomes"]["interested"] == 1
