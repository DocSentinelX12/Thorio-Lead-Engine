from __future__ import annotations

from lead_engine.healing_policy import HealingPolicy


def test_policy_hard_floor_overrides_adaptive_recovery():
    policy = HealingPolicy(protected_standby_floor=2)
    decision = policy.decide(
        criticality=3, confidence=0.99, reversible=True, blast_radius=1,
        redundancy=1, fallback_capacity=1, historical_success=0.99, cascade_risk=0.1,
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "protected_standby_floor"


def test_policy_immediately_contains_cascade_risk():
    decision = HealingPolicy().decide(
        criticality=2, confidence=0.6, reversible=True, blast_radius=1,
        redundancy=3, fallback_capacity=3, historical_success=0.8, cascade_risk=0.95,
    )
    assert decision["containment"] == "immediate_isolate"


def test_policy_requires_serialization_when_independence_is_uncertain():
    decision = HealingPolicy().decide(
        criticality=1, confidence=0.6, reversible=True, blast_radius=2,
        redundancy=2, fallback_capacity=2, historical_success=0.8, cascade_risk=0.2,
    )
    assert decision["concurrency"] == "serialized"
