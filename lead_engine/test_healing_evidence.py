import pytest

from lead_engine.healing_evidence import HealingEvidenceGraph


def test_evidence_graph_persists_authoritative_path_observation_and_relationship(tmp_path):
    db = tmp_path / "evidence.sqlite3"
    graph = HealingEvidenceGraph(str(db))

    observation = graph.record_observation(
        scope_id="path-a",
        entity_type="fabric_path",
        entity_id="path-a",
        source_authority="compute_inventory",
        generation=3,
        confidence=1.0,
        observed_at=10.0,
        payload={"fabric_path_id": "path-a", "state": "FAILED"},
    )
    relationship = graph.record_relationship(
        scope_id="path-a",
        source_type="fabric_path",
        source_id="path-a",
        relation="depends_on",
        target_type="workload",
        target_id="workload-a",
        source_authority="compute_inventory",
        generation=3,
        confidence=1.0,
        observed_at=10.0,
        payload={"fabric_path_id": "path-a"},
    )

    assert observation["entity_id"] == "path-a"
    assert relationship["source_id"] == "path-a"
    assert graph.snapshot("path-a")["path_ids"] == ("path-a",)

    restarted = HealingEvidenceGraph(str(db))
    snapshot = restarted.snapshot("path-a")
    assert snapshot["observations"][0]["payload"]["fabric_path_id"] == "path-a"
    assert snapshot["relationships"][0]["target_id"] == "workload-a"


def test_evidence_graph_rejects_empty_authority_and_path_identity(tmp_path):
    graph = HealingEvidenceGraph(str(tmp_path / "evidence.sqlite3"))

    with pytest.raises(ValueError):
        graph.record_observation(
            scope_id="path-a",
            entity_type="fabric_path",
            entity_id="path-a",
            source_authority="",
            generation=1,
            confidence=1.0,
            observed_at=1.0,
            payload={},
        )

    with pytest.raises(ValueError):
        graph.record_observation(
            scope_id="path-a",
            entity_type="fabric_path",
            entity_id="",
            source_authority="compute_inventory",
            generation=1,
            confidence=1.0,
            observed_at=1.0,
            payload={},
        )
