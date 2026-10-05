"""Autonomous healing plane: evidence-gated coordination above authoritative recovery systems."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any

from .healing_state import HealingState


@dataclass(frozen=True)
class HealingEvidence:
    scope_id: str
    failure_kind: str
    criticality: int
    confidence: float
    blast_radius: int
    reversible: bool
    redundant_capacity: int
    fallback_capacity: int
    historical_success: float
    cascade_risk: float

    def __post_init__(self) -> None:
        if not self.scope_id.strip() or not self.failure_kind.strip():
            raise ValueError("scope_id and failure_kind are required")
        if not 1 <= self.criticality <= 3:
            raise ValueError("criticality must be 1..3")
        if not 0 <= self.confidence <= 1 or not 0 <= self.historical_success <= 1 or not 0 <= self.cascade_risk <= 1:
            raise ValueError("probability fields must be between 0 and 1")
        if self.blast_radius < 0 or self.redundant_capacity < 0 or self.fallback_capacity < 0:
            raise ValueError("capacity and blast radius cannot be negative")


class AutonomousHealingPlane:
    """Make healing decisions while delegating physical truth to lower authorities."""

    def __init__(self, db_path: str = ":memory:", *, protected_standby_floor: int = 1):
        if protected_standby_floor < 0:
            raise ValueError("protected_standby_floor must not be negative")
        self.state = HealingState(db_path)
        self.protected_standby_floor = protected_standby_floor

    @staticmethod
    def _fingerprint(evidence: HealingEvidence) -> str:
        raw = json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def plan(self, evidence: HealingEvidence) -> dict[str, Any]:
        hard_isolation = evidence.cascade_risk >= 0.9 or evidence.blast_radius > 1 or (
            evidence.criticality >= 3 and evidence.confidence >= 0.9 and not evidence.reversible
        )
        containment = "immediate_isolate" if hard_isolation else (
            "quarantine" if evidence.confidence >= 0.75 else "observe"
        )
        standby_allowed = evidence.redundant_capacity > self.protected_standby_floor
        known_good = evidence.confidence >= 0.9 and evidence.historical_success >= 0.8 and evidence.reversible
        safe_recovery = known_good and standby_allowed
        concurrency = (
            "parallel_allowed"
            if evidence.confidence >= 0.9 and evidence.blast_radius <= 1 and evidence.cascade_risk < 0.25
            else "serialized"
        )
        if safe_recovery:
            strategy = "known_good_recovery"
            mode = "recovery"
        else:
            strategy = "degraded_mode"
            mode = "degraded"
            self.state.enter_degraded(scope_id=evidence.scope_id, reason="no-safe-autonomous-recovery")
        generation = 1
        existing = self.state.list_actions()
        scoped = [row for row in existing if row["scope_id"] == evidence.scope_id]
        if scoped:
            generation = max(int(row["generation"]) for row in scoped)
        action = self.state.ensure_action(
            scope_id=evidence.scope_id,
            failure_fingerprint=self._fingerprint(evidence),
            generation=generation,
            strategy=strategy,
        )
        return {
            "action_id": action["action_id"],
            "scope_id": evidence.scope_id,
            "containment": containment,
            "concurrency": concurrency,
            "standby_allowed": standby_allowed,
            "strategy": strategy,
            "mode": mode,
            "evidence": asdict(evidence),
        }
