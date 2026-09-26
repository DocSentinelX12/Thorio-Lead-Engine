"""Adaptive healing policy with immutable safety floors."""

from __future__ import annotations

from typing import Any


class HealingPolicy:
    def __init__(self, *, protected_standby_floor: int = 1):
        if protected_standby_floor < 0:
            raise ValueError("protected_standby_floor must not be negative")
        self.protected_standby_floor = protected_standby_floor

    def decide(
        self, *, criticality: int, confidence: float, reversible: bool,
        blast_radius: int, redundancy: int, fallback_capacity: int,
        historical_success: float, cascade_risk: float,
    ) -> dict[str, Any]:
        if not 1 <= criticality <= 3:
            raise ValueError("criticality must be 1..3")
        probabilities = (confidence, historical_success, cascade_risk)
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("probability values must be between 0 and 1")
        if min(blast_radius, redundancy, fallback_capacity) < 0:
            raise ValueError("capacity and blast radius cannot be negative")

        if cascade_risk >= 0.9 or blast_radius > 1:
            containment = "immediate_isolate"
        elif confidence >= 0.75:
            containment = "quarantine"
        else:
            containment = "observe"

        if redundancy <= self.protected_standby_floor and fallback_capacity <= self.protected_standby_floor:
            return {
                "allowed": False,
                "reason": "protected_standby_floor",
                "containment": containment,
                "concurrency": "serialized",
                "strategy": "degraded_mode",
            }

        known_good = (
            reversible and confidence >= 0.9 and historical_success >= 0.8
            and fallback_capacity > self.protected_standby_floor
        )
        concurrency = (
            "parallel_allowed"
            if confidence >= 0.9 and blast_radius <= 1 and cascade_risk < 0.25
            else "serialized"
        )
        return {
            "allowed": known_good,
            "reason": "known_good_recovery" if known_good else "insufficient_recovery_evidence",
            "containment": containment,
            "concurrency": concurrency,
            "strategy": "known_good_recovery" if known_good else "degraded_mode",
        }
