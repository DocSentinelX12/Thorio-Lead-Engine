from lead_engine.healing_dependencies import HealingDependencyAnalyzer
from lead_engine.healing_evidence import HealingEvidenceGraph
from lead_engine.healing_intelligence import HealingIntelligence


def _graph(tmp_path):
    graph = HealingEvidenceGraph(str(tmp_path / "evidence.sqlite3"))
    graph.record_observation(
        scope_id="path-a", entity_type="fabric_path", entity_id="path-a",
        source_authority="compute_inventory", generation=1, confidence=1.0,
        observed_at=10.0, payload={"fabric_path_id": "path-a", "state": "FAILED", "failure_domain": "rack-a"},
    )
    graph.record_relationship(
        scope_id="path-a", source_type="fabric_path", source_id="path-a",
        relation="supports", target_type="workload", target_id="workload-a",
        source_authority="placement", generation=1, confidence=1.0,
        observed_at=10.0, payload={"fabric_path_id": "path-a"},
    )
    return graph


def test_healing_intelligence_orders_recovery_after_authoritative_path_evidence(tmp_path):
    graph = _graph(tmp_path)
    intelligence = HealingIntelligence(
        graph=graph,
        dependencies=HealingDependencyAnalyzer(graph),
        db_path=str(tmp_path / "intelligence.sqlite3"),
    )
    plan = intelligence.plan(
        scope_id="path-a",
        generation=1,
        strategy="recover_exact_path",
        criticality=3,
        confidence=0.98,
        reversible=True,
        cascade_risk=0.1,
        redundant_capacity=True,
        standby_capacity_available=True,
        fabric_path_id="path-a",
    )
    assert [step["kind"] for step in plan["steps"]] == [
        "physical_reverify",
        "active_measurement",
        "route_reconcile",
        "workload_reconcile",
        "closure",
    ]
    assert all(step["fabric_path_id"] == "path-a" for step in plan["steps"])
    assert plan["steps"][1]["depends_on"] == (plan["steps"][0]["step_id"],)


def test_healing_intelligence_serializes_conflicting_scope_and_preserves_standby(tmp_path):
    graph = _graph(tmp_path)
    intelligence = HealingIntelligence(
        graph=graph,
        dependencies=HealingDependencyAnalyzer(graph),
        db_path=str(tmp_path / "intelligence.sqlite3"),
    )
    intelligence.plan(
        scope_id="path-a",
        generation=1,
        strategy="recover_exact_path",
        criticality=3,
        confidence=0.98,
        reversible=True,
        cascade_risk=0.1,
        redundant_capacity=True,
        standby_capacity_available=True,
        fabric_path_id="path-a",
    )
    blocked = intelligence.plan(
        scope_id="path-a",
        generation=2,
        strategy="recover_exact_path",
        criticality=3,
        confidence=0.98,
        reversible=True,
        cascade_risk=0.1,
        redundant_capacity=False,
        standby_capacity_available=False,
        fabric_path_id="path-a",
    )
    assert blocked["mode"] == "SERIALIZED"
    assert blocked["requires_degraded_mode"] is True


def test_healing_intelligence_reconciles_after_restart(tmp_path):
    graph = _graph(tmp_path)
    db = str(tmp_path / "intelligence.sqlite3")
    first = HealingIntelligence(graph=graph, dependencies=HealingDependencyAnalyzer(graph), db_path=db)
    plan = first.plan(
        scope_id="path-a",
        generation=1,
        strategy="recover_exact_path",
        criticality=2,
        confidence=0.9,
        reversible=True,
        cascade_risk=0.1,
        redundant_capacity=True,
        standby_capacity_available=True,
        fabric_path_id="path-a",
    )
    restarted = HealingIntelligence(graph=graph, dependencies=HealingDependencyAnalyzer(graph), db_path=db)
    assert restarted.reconcile(
        plan_id=plan["plan_id"],
        authoritative_state={"path_id": "path-a", "state": "MEASURED", "allow_routing": True},
        observed_steps=("physical_reverify", "active_measurement", "route_reconcile"),
    )["decision"] == "RESUME"
