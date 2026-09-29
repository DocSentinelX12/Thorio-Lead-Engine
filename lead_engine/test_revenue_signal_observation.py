from .revenue_signal_observation import (
    build_revenue_signal_observation,
    build_revenue_signal_observations,
)


def test_observation_contract_preserves_identity_source_evidence_and_timestamp():
    lead = {
        "opportunity_id": "opp-123",
        "fingerprint": "opp-123",
        "company": "Acme",
        "contact_name": "Jane Doe",
        "contact_title": "CTO",
        "source": "LinkedIn",
        "source_id": "post-42",
        "source_url": "https://linkedin.example/post-42",
        "url": "https://acme.example/careers/42",
        "signal": "looking for a development partner",
        "evidence": "We are looking for a development partner for an MVP.",
        "signal_type": "commercial_intent",
        "signal_matches": ["looking for a development partner", "need an mvp"],
        "signal_context": ["We are looking for a development partner for an MVP."],
        "discovered_at": "2026-09-28T20:00:00Z",
    }
    result = build_revenue_signal_observation(lead)
    assert result["opportunity_id"] == "opp-123"
    assert result["fingerprint"] == "opp-123"
    assert result["company"] == {"name": "Acme"}
    assert result["person"] == {"name": "Jane Doe", "title": "CTO"}
    assert result["source"] == "LinkedIn"
    assert result["source_id"] == "post-42"
    assert result["source_url"] == "https://linkedin.example/post-42"
    assert result["observed_at"] == "2026-09-28T20:00:00Z"
    assert result["evidence"]["text"] == lead["evidence"]
    assert result["signal"]["type"] == "commercial_intent"
    assert result["signal"]["matches"] == lead["signal_matches"]
    assert result["signal"]["context"] == lead["signal_context"]
    assert result["provenance"]["canonical_evidence_key"]
    assert result["provenance"]["verification_status"] == "observed_evidence"


def test_observation_contract_preserves_route_relevance_without_selecting_a_route():
    lead = {
        "opportunity_id": "opp-route",
        "fingerprint": "opp-route",
        "company": "Acme",
        "source": "Research",
        "source_id": "research-1",
        "source_url": "https://acme.example/news",
        "evidence": "Acme is seeking a technology partner.",
        "signal": "seeking a technology partner",
        "signal_type": "commercial_intent",
        "eligible_routes": ["Shiftr", "Astrivon Labs"],
        "route_research": {"routes": {"Shiftr": {"evidence": [{"canonical_evidence_key": "ev-shiftr"}]}}},
    }
    result = build_revenue_signal_observation(lead)
    assert result["route_relevance"]["eligible_routes"] == ["Shiftr", "Astrivon Labs"]
    assert result["route_relevance"]["researched_routes"] == ["Shiftr"]
    assert "selected_route" not in result["route_relevance"]
    assert "score" not in result["route_relevance"]


def test_observation_contract_preserves_supporting_and_contradictory_refs_without_inventing_them():
    lead = {
        "opportunity_id": "opp-evidence",
        "fingerprint": "opp-evidence",
        "company": "Acme",
        "source": "Research",
        "source_id": "research-2",
        "evidence": "Current commercial need observed.",
        "signal": "commercial need",
        "supporting_evidence_refs": ["ev-1", "ev-2"],
        "contradictory_evidence_refs": ["ev-3"],
        "research_gaps": {"missing_sections": ["budget", "decision_process"], "unknowns": ["authority"]},
    }
    result = build_revenue_signal_observation(lead)
    assert result["supporting_evidence_refs"] == ["ev-1", "ev-2"]
    assert result["contradictory_evidence_refs"] == ["ev-3"]
    assert result["research_gaps"] == lead["research_gaps"]


def test_observation_contract_does_not_invent_missing_evidence_or_identity():
    result = build_revenue_signal_observation({
        "opportunity_id": "opp-minimal",
        "fingerprint": "opp-minimal",
        "company": "Acme",
        "source": "Source",
    })
    assert result["opportunity_id"] == "opp-minimal"
    assert result["company"] == {"name": "Acme"}
    assert result["person"] == {}
    assert result["evidence"]["text"] == ""
    assert result["signal"]["matches"] == []
    assert result["route_relevance"]["eligible_routes"] == []
    assert result["supporting_evidence_refs"] == []
    assert result["contradictory_evidence_refs"] == []
    assert result["research_gaps"] == {}


def test_observation_collection_keeps_one_contract_per_input_observation():
    leads = [
        {"opportunity_id": "opp-1", "fingerprint": "opp-1", "company": "One", "source": "A", "evidence": "Evidence one"},
        {"opportunity_id": "opp-2", "fingerprint": "opp-2", "company": "Two", "source": "B", "evidence": "Evidence two"},
    ]
    result = build_revenue_signal_observations(leads)
    assert [item["opportunity_id"] for item in result] == ["opp-1", "opp-2"]


def test_observation_contract_rejects_mismatched_canonical_identity():
    try:
        build_revenue_signal_observation({
            "opportunity_id": "opp-1",
            "fingerprint": "opp-2",
            "company": "Acme",
        })
    except ValueError as exc:
        assert "opportunity_id and fingerprint must match" in str(exc)
    else:
        raise AssertionError("mismatched canonical identity must be rejected")
