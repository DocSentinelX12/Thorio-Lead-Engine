from .unified_opportunity_signal_graph import (
    build_unified_opportunity_signal_graph,
    validate_unified_opportunity_signal_graph,
)


def _lead():
    return {
        "fingerprint": "graph-opportunity-1",
        "opportunity_id": "graph-opportunity-1",
        "company": "Acme",
        "source": "LinkedIn",
        "source_id": "post-1",
        "url": "https://example.com/post-1",
        "signal": "Acme is looking for a development partner.",
        "evidence": "We are looking for a development partner for our product.",
        "signal_type": "commercial_intent",
        "signal_matches": ["looking for a development partner"],
        "signal_context": ["We are looking for a development partner for our product."],
        "discovered_at": "2026-09-29T12:00:00+00:00",
        "evidence_events": [
            {
                "source_id": "evt-1",
                "source_url": "https://example.com/post-1",
                "signal": "Acme is looking for a development partner.",
                "evidence": "We are looking for a development partner for our product.",
                "observed_at": "2026-09-29T12:00:00+00:00",
            }
        ],
        "business_need_research": {
            "verification_status": "verified",
            "evidence": [
                {
                    "url": "https://example.com/need",
                    "evidence": "Acme needs implementation capacity.",
                    "observed_at": "2026-09-29T12:00:00+00:00",
                    "verification_status": "verified",
                }
            ],
        },
        "qualification_results": {"Shiftr": {"qualified": True}},
        "qualified": True,
        "eligible_routes": ["Shiftr"],
        "outreach_route": "Shiftr",
        "commercial_strategy": {"approach": "evidence_first"},
        "outreach_history": [
            {
                "action_id": "action-1",
                "conversation_id": "conversation-1",
                "route": "Shiftr",
                "channel": "email",
                "status": "sent",
            }
        ],
        "conversation_events": [
            {
                "event_id": "event-1",
                "at": "2026-09-29T13:00:00+00:00",
                "outcome": "interested",
                "text": "Yes, let's talk.",
            }
        ],
        "revenue_lifecycle_state": "conversation_active",
        "sales_eligibility": "eligible",
    }


def test_unified_graph_connects_identity_signal_evidence_research_route_outreach_outcome_and_revenue():
    graph = build_unified_opportunity_signal_graph([_lead()], generated_at="2026-09-29T14:00:00+00:00")
    validate_unified_opportunity_signal_graph(graph)
    types = {node["type"] for node in graph["nodes"].values()}
    assert {"opportunity", "source_observation", "signal_observation", "signal", "signal_evidence", "evidence", "research", "qualification", "route", "outreach_action", "closer_strategy", "outcome", "revenue_attribution"} <= types
    assert any(
        edge["type"] == "signal_observed_with_outcome" and edge["association_only"] is True
        for edge in graph["edges"]
    )
    evidence = [node for node in graph["nodes"].values() if node["type"] == "signal_evidence"]
    assert any(
        node["exact_evidence"] == "We are looking for a development partner for our product."
        and node["source_url"] == "https://example.com/post-1"
        for node in evidence
    )


def test_unified_graph_rejects_dangling_edges():
    graph = build_unified_opportunity_signal_graph([_lead()])
    graph["edges"].append({
        "id": "edge-bad",
        "type": "broken",
        "from": "missing",
        "to": next(iter(graph["nodes"])),
    })
    try:
        validate_unified_opportunity_signal_graph(graph)
    except ValueError as exc:
        assert "dangling edge" in str(exc)
    else:
        raise AssertionError("dangling edge must be rejected")

    
def test_unified_graph_does_not_treat_outreach_delivery_status_as_outcome():
    lead = _lead()
    lead["conversation_events"] = []
    lead["commercial_outcome"] = {}
    lead["revenue_lifecycle_state"] = ""
    graph = build_unified_opportunity_signal_graph([lead])
    outcome_nodes = [
        node for node in graph["nodes"].values()
        if node["type"] == "outcome"
    ]
    assert outcome_nodes == []
