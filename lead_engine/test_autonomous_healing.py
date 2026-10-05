from __future__ import annotations

from lead_engine.autonomous_healing import AutonomousHealingPlane, HealingEvidence


def test_healing_plane_contains_high_risk_failure_and_enters_degraded_mode_when_no_safe_strategy(tmp_path):
    plane = AutonomousHealingPlane(str(tmp_path / "healing.sqlite3"))
    evidence = HealingEvidence(
        scope_id="fabric:path-a",
        failure_kind="physical_failure",
        criticality=3,
        confidence=0.99,
        blast_radius=1,
        reversible=True,
        redundant_capacity=0,
        fallback_capacity=0,
        historical_success=0.0,
        cascade_risk=0.99,
    )
    decision = plane.plan(evidence)
    assert decision["containment"] == "immediate_isolate"
    assert decision["mode"] == "degraded"


def test_healing_plane_allows_known_good_reversible_recovery_above_safety_floor(tmp_path):
    plane = AutonomousHealingPlane(str(tmp_path / "healing.sqlite3"))
    evidence = HealingEvidence(
        scope_id="fabric:path-b",
        failure_kind="transient_failure",
        criticality=2,
        confidence=0.95,
        blast_radius=1,
        reversible=True,
        redundant_capacity=2,
        fallback_capacity=2,
        historical_success=0.9,
        cascade_risk=0.1,
    )
    decision = plane.plan(evidence)
    assert decision["containment"] == "quarantine"
    assert decision["mode"] == "recovery"
    assert decision["strategy"] == "known_good_recovery"


def test_healing_plane_serializes_uncertain_scopes_and_allows_independent_actions(tmp_path):
    plane = AutonomousHealingPlane(str(tmp_path / "healing.sqlite3"))
    first = HealingEvidence(
        scope_id="scope-a", failure_kind="unknown", criticality=1, confidence=0.51,
        blast_radius=2, reversible=True, redundant_capacity=1, fallback_capacity=1,
        historical_success=0.5, cascade_risk=0.2,
    )
    second = HealingEvidence(
        scope_id="scope-b", failure_kind="unknown", criticality=1, confidence=0.51,
        blast_radius=2, reversible=True, redundant_capacity=1, fallback_capacity=1,
        historical_success=0.5, cascade_risk=0.2,
    )
    assert plane.plan(first)["concurrency"] == "serialized"
    independent = HealingEvidence(
        scope_id="scope-c", failure_kind="known", criticality=1, confidence=0.99,
        blast_radius=1, reversible=True, redundant_capacity=2, fallback_capacity=2,
        historical_success=0.95, cascade_risk=0.01,
    )
    assert plane.plan(independent)["concurrency"] == "parallel_allowed"


def test_healing_plane_preserves_standby_floor(tmp_path):
    plane = AutonomousHealingPlane(str(tmp_path / "healing.sqlite3"), protected_standby_floor=1)
    evidence = HealingEvidence(
        scope_id="scope-d", failure_kind="transient", criticality=2, confidence=0.99,
        blast_radius=1, reversible=True, redundant_capacity=0, fallback_capacity=0,
        historical_success=0.9, cascade_risk=0.1,
    )
    decision = plane.plan(evidence)
    assert decision["standby_allowed"] is False
    assert decision["mode"] == "degraded"
