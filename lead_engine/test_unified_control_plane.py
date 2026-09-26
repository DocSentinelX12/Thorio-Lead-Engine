from __future__ import annotations

import tempfile

import pytest

from .unified_control_plane import UnifiedControlPlane


def ev(cp, source, kind, subject, t, confidence=0.95):
    return cp.record_evidence(source=source, kind=kind, subject=subject, observed_at=t, payload={"value": t}, confidence=confidence, provenance=f"{source}:{kind}:{subject}:{t}")


def test_adaptive_threshold_scales_with_risk():
    cp = UnifiedControlPlane()
    subject = "gpu-pair:a-b"
    e1, e2 = ev(cp, "path", "telemetry", subject, 1), ev(cp, "execution", "outcome", subject, 2)
    assert cp.authorize(action="route", subject=subject, evidence=[e1, e2]).authorized
    decision = cp.authorize(action="migration", subject=subject, evidence=[e1, e2], workload_criticality=3)
    assert not decision.authorized
    assert decision.required_source_count > 2


def test_same_source_cannot_satisfy_independence():
    cp = UnifiedControlPlane()
    subject = "gpu-pair:a-b"
    e1, e2 = ev(cp, "telemetry", "bandwidth", subject, 1), ev(cp, "telemetry", "latency", subject, 2)
    decision = cp.authorize(action="route", subject=subject, evidence=[e1, e2])
    assert not decision.authorized
    assert "independent evidence" in decision.reason


def test_safety_floor_and_fallback_are_hard_gates():
    cp = UnifiedControlPlane()
    subject = "workload:critical"
    evidence = [ev(cp, "path", "health", subject, 1), ev(cp, "execution", "health", subject, 2)]
    assert cp.authorize(action="route", subject=subject, evidence=evidence, safety_ok=False).reason == "hard safety floor failed"
    assert "fallback" in cp.authorize(action="route", subject=subject, evidence=evidence, fallback_available=False).reason


def test_evidence_is_immutable_and_deduplicated():
    cp = UnifiedControlPlane()
    first = ev(cp, "path", "health", "path:a", 1)
    second = ev(cp, "path", "health", "path:a", 1)
    assert first.evidence_id == second.evidence_id
    assert len(cp.evidence_for("path:a")) == 1


def setup_strategies(cp):
    cp.register_capability(capability="placement", incumbent_strategy_id="champion-v1", fallback_strategy_id="champion-v1", minimum_availability=0.9, minimum_reliability=0.9)
    cp.register_strategy(strategy_id="champion-v1", capability="placement", role="champion")
    cp.register_strategy(strategy_id="challenger-v2", capability="placement", role="challenger")


def test_challenger_cannot_replace_incumbent_from_one_success():
    cp = UnifiedControlPlane()
    setup_strategies(cp)
    for i in range(20):
        cp.observe_strategy(strategy_id="champion-v1", success=True, performance=100, safety_ok=True, observed_at=i, evidence=[ev(cp, "execution", "champion", f"c:{i}", i)])
    cp.observe_strategy(strategy_id="challenger-v2", success=True, performance=120, safety_ok=True, observed_at=100, evidence=[ev(cp, "execution", "challenger", "one", 100)])
    assert not cp.strategy_decision(strategy_id="challenger-v2").eligible


def test_proven_challenger_promotes_and_preserves_fallback():
    cp = UnifiedControlPlane()
    setup_strategies(cp)
    for i in range(20):
        cp.observe_strategy(strategy_id="champion-v1", success=True, performance=100, safety_ok=True, observed_at=i, evidence=[ev(cp, "execution", "champion", f"c:{i}", i)])
        cp.observe_strategy(strategy_id="challenger-v2", success=True, performance=120, safety_ok=True, observed_at=i, evidence=[ev(cp, "execution", "challenger", f"x:{i}", i)])
    assert cp.strategy_decision(strategy_id="challenger-v2").eligible
    assert cp.promote(strategy_id="challenger-v2").eligible
    state = cp.capability_state("placement")
    assert state["incumbent_strategy_id"] == "challenger-v2"
    assert state["fallback_strategy_id"] == "champion-v1"
    assert state["fallback_available"]


def test_unsafe_challenger_never_promotes():
    cp = UnifiedControlPlane()
    setup_strategies(cp)
    for i in range(20):
        cp.observe_strategy(strategy_id="champion-v1", success=True, performance=100, safety_ok=True, observed_at=i, evidence=[ev(cp, "execution", "champion", f"c:{i}", i)])
        cp.observe_strategy(strategy_id="challenger-v2", success=True, performance=140, safety_ok=False, observed_at=i, evidence=[ev(cp, "execution", "unsafe", f"x:{i}", i)])
    assert not cp.strategy_decision(strategy_id="challenger-v2").eligible


def test_counterfactual_and_outcome_are_durable():
    cp = UnifiedControlPlane()
    subject = "workload:x"
    evidence = [ev(cp, "path", "health", subject, 1), ev(cp, "execution", "health", subject, 2)]
    decision = cp.authorize(action="route", subject=subject, evidence=evidence)
    assert cp.record_counterfactual(decision_id=decision.decision_id, strategy_id="route-v2", expected_outcome={"latency_us": 12}, confidence=0.8, evidence=evidence).startswith("counterfactual:")
    assert cp.record_outcome(decision_id=decision.decision_id, outcome="success", observed_at=3, metrics={"latency_us": 10}, evidence=evidence, strategy_id="route-v1").startswith("outcome:")


def test_novel_situation_falls_back_without_evidence():
    cp = UnifiedControlPlane()
    decision = cp.authorize(action="placement", subject="novel:topology", evidence=[])
    assert not decision.authorized
    assert "insufficient" in decision.reason


def test_persistence_survives_reopen():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
        cp = UnifiedControlPlane(handle.name)
        recorded = ev(cp, "path", "health", "path:a", 1)
        cp2 = UnifiedControlPlane(handle.name)
        assert cp2.evidence_for("path:a")[0].evidence_id == recorded.evidence_id


def test_invalid_strategy_role_is_rejected():
    cp = UnifiedControlPlane()
    cp.register_capability(capability="routing", incumbent_strategy_id="v1", fallback_strategy_id="v1")
    with pytest.raises(ValueError):
        cp.register_strategy(strategy_id="v2", capability="routing", role="experimental")
