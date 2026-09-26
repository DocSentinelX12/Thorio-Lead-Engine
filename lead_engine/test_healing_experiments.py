from __future__ import annotations

import pytest

from lead_engine.healing_experiments import HealingExperimentError, HealingExperimentManager


def test_champion_remains_available_while_challenger_runs(tmp_path):
    mgr = HealingExperimentManager(str(tmp_path / "experiments.sqlite3"))
    ctx = mgr.context_key(fabric_path_id="path-1", failure_domain="fd-a", workload_class="training")
    champion = mgr.register_champion(context_key=ctx, strategy="known-good")
    exp = mgr.start_challenger(context_key=ctx, challenger_strategy="candidate-v2")
    state = mgr.select(context_key=ctx)
    assert champion["role"] == "CHAMPION"
    assert exp["state"] == "RUNNING"
    assert state["strategy"] == "known-good"
    assert state["challenger_isolated"] is True


def test_promotion_requires_sustained_contextual_evidence_and_safety(tmp_path):
    mgr = HealingExperimentManager(str(tmp_path / "experiments.sqlite3"))
    ctx = mgr.context_key(fabric_path_id="path-2", failure_domain="fd-a", workload_class="training")
    mgr.register_champion(context_key=ctx, strategy="known-good")
    exp = mgr.start_challenger(context_key=ctx, challenger_strategy="candidate-v2")
    for i in range(5):
        mgr.record_outcome(
            experiment_id=exp["experiment_id"], strategy="known-good",
            success=(i < 4), evidence={"path": "path-2", "sample": i},
            observed_at=float(i + 1),
        )
        mgr.record_outcome(
            experiment_id=exp["experiment_id"], strategy="candidate-v2",
            success=True, reversible=True,
            evidence={"path": "path-2", "sample": i},
            observed_at=float(i + 1),
        )
    evaluation = mgr.evaluate(experiment_id=exp["experiment_id"])
    assert evaluation["promotion_eligible"] is True
    promoted = mgr.promote(experiment_id=exp["experiment_id"])
    assert promoted["champion"]["strategy"] == "candidate-v2"
    assert promoted["strategies"][0]["state"] in {"RETIRED", "ACTIVE"}


def test_safety_violation_blocks_promotion_even_when_successful(tmp_path):
    mgr = HealingExperimentManager(str(tmp_path / "experiments.sqlite3"))
    ctx = mgr.context_key(fabric_path_id="path-3")
    mgr.register_champion(context_key=ctx, strategy="known-good")
    exp = mgr.start_challenger(context_key=ctx, challenger_strategy="unsafe")
    for i in range(5):
        mgr.record_outcome(
            experiment_id=exp["experiment_id"], strategy="known-good", success=True,
            evidence={"sample": i}, observed_at=float(i + 1),
        )
        mgr.record_outcome(
            experiment_id=exp["experiment_id"], strategy="unsafe", success=True,
            safety_violation=(i == 2), evidence={"sample": i}, observed_at=float(i + 1),
        )
    assert mgr.evaluate(experiment_id=exp["experiment_id"])["promotion_eligible"] is False
    with pytest.raises(HealingExperimentError):
        mgr.promote(experiment_id=exp["experiment_id"])


def test_failed_challenger_rolls_back_to_original_champion(tmp_path):
    mgr = HealingExperimentManager(str(tmp_path / "experiments.sqlite3"))
    ctx = mgr.context_key(fabric_path_id="path-4")
    mgr.register_champion(context_key=ctx, strategy="known-good")
    exp = mgr.start_challenger(context_key=ctx, challenger_strategy="candidate")
    mgr.record_outcome(experiment_id=exp["experiment_id"], strategy="candidate", success=False, evidence={"failure": "timeout"})
    state = mgr.rollback(experiment_id=exp["experiment_id"], reason="candidate regression")
    assert state["champion"]["strategy"] == "known-good"
    assert all(s["state"] != "ACTIVE" or s["role"] == "CHAMPION" for s in state["strategies"])


def test_experiment_state_survives_restart(tmp_path):
    path = str(tmp_path / "experiments.sqlite3")
    mgr = HealingExperimentManager(path)
    ctx = mgr.context_key(fabric_path_id="path-5", failure_domain="fd-b")
    mgr.register_champion(context_key=ctx, strategy="known-good")
    exp = mgr.start_challenger(context_key=ctx, challenger_strategy="candidate")
    mgr.record_outcome(experiment_id=exp["experiment_id"], strategy="candidate", success=True, evidence={"x": 1}, observed_at=1)
    del mgr
    restored = HealingExperimentManager(path)
    status = restored.status(context_key=ctx)
    assert status["champion"]["strategy"] == "known-good"
    assert status["challengers"][0]["strategy"] == "candidate"
