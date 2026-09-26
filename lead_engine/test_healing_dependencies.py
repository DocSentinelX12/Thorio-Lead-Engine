from lead_engine.healing_dependencies import HealingDependencyAnalyzer
from lead_engine.healing_evidence import HealingEvidenceGraph


def _graph(tmp_path):
    return HealingEvidenceGraph(str(tmp_path / "evidence.sqlite3"))


def test_dependency_analyzer_traverses_transitive_impact_and_preserves_provenance(tmp_path):
    graph = _graph(tmp_path)
    graph.record_observation(
        scope_id="path-a", entity_type="fabric_path", entity_id="path-a",
        source_authority="compute_inventory", generation=1, confidence=1.0,
        observed_at=10.0, payload={"fabric_path_id": "path-a", "failure_domain": "rack-a"},
    )
    graph.record_relationship(
        scope_id="path-a", source_type="fabric_path", source_id="path-a",
        relation="supports", target_type="workload", target_id="workload-a",
        source_authority="placement", generation=1, confidence=1.0,
        observed_at=10.0, payload={"fabric_path_id": "path-a"},
    )
    graph.record_relationship(
        scope_id="path-a", source_type="workload", source_id="workload-a",
        relation="allocated_to", target_type="node", target_id="node-a",
        source_authority="placement", generation=1, confidence=1.0,
        observed_at=10.0, payload={"failure_domain": "rack-a"},
    )

    result = HealingDependencyAnalyzer(graph).impact("path-a")
    assert result["affected_entities"] == (
        ("fabric_path", "path-a"),
        ("node", "node-a"),
        ("workload", "workload-a"),
    )
    assert result["failure_domains"] == ("rack-a",)
    assert result["dependency_edges"][0]["source_authority"] == "placement"


def test_failure_correlation_does_not_merge_unrelated_failure_domains(tmp_path):
    graph = _graph(tmp_path)
    for scope, domain, when in (("path-a", "rack-a", 10.0), ("path-b", "rack-b", 10.0)):
        graph.record_observation(
            scope_id=scope, entity_type="fabric_path", entity_id=scope,
            source_authority="compute_inventory", generation=1, confidence=1.0,
            observed_at=when, payload={"fabric_path_id": scope, "failure_domain": domain, "state": "FAILED"},
        )
    result = HealingDependencyAnalyzer(graph).failure_episode("path-a", 10.0)
    assert result["correlated_scopes"] == ("path-a",)


def test_failure_correlation_uses_shared_dependency(tmp_path):
    graph = _graph(tmp_path)
    for scope in ("path-a", "path-b"):
        graph.record_observation(
            scope_id=scope, entity_type="fabric_path", entity_id=scope,
            source_authority="compute_inventory", generation=1, confidence=1.0,
            observed_at=10.0, payload={"fabric_path_id": scope, "state": "FAILED"},
        )
    graph.record_relationship(
        scope_id="path-a", source_type="fabric_path", source_id="path-a",
        relation="shares_failure_domain", target_type="domain", target_id="domain-x",
        source_authority="compute_inventory", generation=1, confidence=1.0,
        observed_at=10.0, payload={"failure_domain": "domain-x"},
    )
    graph.record_relationship(
        scope_id="path-b", source_type="fabric_path", source_id="path-b",
        relation="shares_failure_domain", target_type="domain", target_id="domain-x",
        source_authority="compute_inventory", generation=1, confidence=1.0,
        observed_at=10.0, payload={"failure_domain": "domain-x"},
    )
    result = HealingDependencyAnalyzer(graph).failure_episode("path-a", 10.0)
    assert result["correlated_scopes"] == ("path-a", "path-b")
