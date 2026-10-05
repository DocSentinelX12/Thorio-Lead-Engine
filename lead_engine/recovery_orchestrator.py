"""Durable exact-path recovery orchestration."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .compute_inventory import ComputeInventory


class RecoveryOrchestrator:
    """Coordinate discovery, leasing, execution, and durable recovery state."""

    def __init__(self, inventory: ComputeInventory):
        self.inventory = inventory

    def discover(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Discover every currently triggered exact path without dropping backlog."""
        return self.inventory.enqueue_active_path_recovery_actions(now=now)

    def due(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Return every durable recovery action currently eligible for execution."""
        return self.inventory.due_active_path_recovery_actions(now=now)

    def claim(self, *, action_id: str, owner: str, now: float | None = None, lease_seconds: float = 300.0) -> dict[str, Any] | None:
        """Claim one due action through the inventory transactional lease."""
        return self.inventory.claim_active_path_recovery_action(
            action_id=action_id, owner=owner, now=now, lease_seconds=lease_seconds
        )

    def execute(
        self,
        *,
        action_id: str,
        owner: str,
        physical_evidence: Sequence[Mapping[str, Any]],
        active_measurement: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        observed_at: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Execute one exact-path recovery action through authoritative gates."""
        return self.inventory.execute_active_path_recovery_action(
            action_id=action_id,
            owner=owner,
            physical_evidence=physical_evidence,
            active_measurement=active_measurement,
            evidence=evidence,
            observed_at=observed_at,
            now=now,
        )

    def run_due(
        self,
        *,
        owner: str,
        evidence_provider: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Execute all due actions with evidence supplied per exact action."""
        results: list[dict[str, Any]] = []
        for action in self.due(now=now):
            payload = dict(evidence_provider(action))
            physical_evidence = payload.pop("physical_evidence", ())
            active_measurement = payload.pop("active_measurement", None)
            evidence = payload.pop("evidence", None)
            observed_at = payload.pop("observed_at", now)
            if payload:
                raise ValueError(
                    "evidence provider returned unsupported fields: "
                    + ", ".join(sorted(str(key) for key in payload))
                )
            try:
                result = self.execute(
                    action_id=str(action["action_id"]),
                    owner=owner,
                    physical_evidence=physical_evidence,
                    active_measurement=active_measurement,
                    evidence=evidence,
                    observed_at=observed_at,
                    now=now,
                )
            except Exception as exc:
                result = {
                    "action_id": action["action_id"],
                    "path_id": action["path_id"],
                    "state": "EXECUTION_ERROR",
                    "allow_routing": False,
                    "error": str(exc),
                }
            results.append(result)
        return results
