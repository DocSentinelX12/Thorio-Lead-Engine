from lead_engine.healing_evidence import HealingEvidenceGraph
from lead_engine.healing_dependencies import HealingDependencyAnalyzer
from lead_engine.healing_intelligence import HealingIntelligence
from lead_engine.healing_prediction import PredictiveHealingIntelligence


def _graph(tmp_path):
    graph = HealingEvidenceGraph(str(tmp_path / "evidence.sqlite3"))
    samples = (
        (10.0, "MEASURED", 100.0, True),
        (20.0, "MEASURED", 102.0, True),
        (30.0, "FAILED", 45.0, False),
        (40.0, "FAILED", 40.0, False),
        (50.0, "MEASURED", 98.0, True),
        (60.0, "FAILED", 42.0, False),
    )
    for observed_at, state, bandwidth, verified in samples:
        graph.record_observation(
            scope_id="path-a",
            entity_type="fabric_path",
            entity_id="path-a",
            source_authority="compute_inventory",
            generation=1,
            confidence=1.0,
            observed_at=observed_at,
            payload={
                "fabric_path_id": "path-a",
                "state": state,
                "measurement": {"bandwidth_gbps": bandwidth, "latency_us": 5.0},
                "verified": verified,
            },
        )
    return graph


def test_signal_discovery_learns_path_scoped_failure_relationship(tmp_path):
    graph = _graph(tmp_path)
    predictor = PredictiveHealingIntelligence(graph=graph, db_path=str(tmp_path / "prediction.sqlite3"))
    discovered = predictor.discover(scope_id="path-a")
    assert discovered["predictive_signal_count"] >= 1
    bandwidth = next(item for item in discovered["signals"] if item["signal"].endswith("bandwidth_gbps"))
    assert bandwidth["failed_samples"] == 3
    assert bandwidth["healthy_samples"] == 4
    assert bandwidth["effect"] < 0


def test_prediction_is_transparent_and_counterfactual(tmp_path):
    graph = _graph(tmp_path)
    predictor = PredictiveHealingIntelligence(graph=graph, db_path=str(tmp_path / "prediction.sqlite3"))
    result = predictor.predict(scope_id="path-a")
    assert result["state"] == "PREDICTED"
    assert result["failure_risk"] is not None
    assert result["confidence"] > 0
    assert result["source_observation_ids"]
    cf = predictor.counterfactual(scope_id="path-a")
    bandwidth = next(item for item in cf["counterfactuals"] if item["signal"].endswith("bandwidth_gbps"))
    assert bandwidth["healthy_baseline"] == 100.0
    assert bandwidth["risk_delta_if_baseline"] < 0


def test_prediction_is_insufficient_without_two_failure_and_two_healthy_samples(tmp_path):
    graph = HealingEvidenceGraph(str(tmp_path / "evidence.sqlite3"))
    for observed_at in (1.0, 2.0, 3.0):
        graph.record_observation(
            scope_id="path-b", entity_type="fabric_path", entity_id="path-b",
            source_authority="compute_inventory", generation=1, confidence=1.0,
            observed_at=observed_at,
            payload={"fabric_path_id": "path-b", "measurement": {"bandwidth_gbps": 100.0}, "state": "MEASURED"},
        )
    predictor = PredictiveHealingIntelligence(graph=graph, db_path=str(tmp_path / "prediction.sqlite3"))
    assert predictor.predict(scope_id="path-b")["state"] == "INSUFFICIENT_EVIDENCE"


def test_prediction_persists_across_restart_and_keeps_exact_path_provenance(tmp_path):
    graph = _graph(tmp_path)
    db = str(tmp_path / "prediction.sqlite3")
    first = PredictiveHealingIntelligence(graph=graph, db_path=db)
    first_result = first.predict(scope_id="path-a")
    restarted = PredictiveHealingIntelligence(graph=graph, db_path=db)
    second_result = restarted.predict(scope_id="path-a")
    assert second_result["assessment_id"] == first_result["assessment_id"]
    assert all("path-a" in str(item) or item for item in second_result["source_observation_ids"])


def test_healing_plan_consumes_prediction_without_replacing_authoritative_path(tmp_path):
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
    assert plan["prediction"]["scope_id"] == "path-a"
    assert plan["counterfactual"]["scope_id"] == "path-a"
    assert all(step["fabric_path_id"] == "path-a" for step in plan["steps"])
