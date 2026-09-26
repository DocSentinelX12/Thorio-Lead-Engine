"""Read-only integration gateway for authoritative GPU healing evidence.

This module coordinates existing authorities without creating a competing source
of physical, active-path, or recovery truth.
"""

from __future__ import annotations

from typing import Any

from .compute_inventory import ComputeInventory
from .recovery_orchestrator import RecoveryOrchestrator


class HealingAuthorityError(RuntimeError):
    """Raised when authoritative healing evidence cannot be established."""


class HealingAuthorityGateway:
    """Expose one exact-path evidence view across existing authorities."""

    AUTHORITIES = (
        "compute_inventory",
        "active_path_intelligence",
        "recovery_orchestrator",
    )

    def __init__(
        self,
        *,
        inventory: ComputeInventory,
        recovery_orchestrator: RecoveryOrchestrator,
    ) -> None:
        if recovery_orchestrator.inventory is not inventory:
            raise ValueError("recovery orchestrator must use the same compute inventory authority")
        self.inventory = inventory
        self.recovery_orchestrator = recovery_orchestrator


    def recover_path(
        self,
        *,
        path_id: str,
        owner: str,
        physical_evidence: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        active_measurement: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        observed_at: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Delegate one exact-path recovery to the existing recovery authority."""
        snapshot = self.path(path_id)
        exact_path_id = snapshot["path_id"]
        self.recovery_orchestrator.discover(now=now)
        due = tuple(
            action
            for action in self.recovery_orchestrator.due(now=now)
            if str(action.get("path_id") or "") == exact_path_id
        )
        if not due:
            raise HealingAuthorityError(
                f"no due authoritative recovery action exists for path: {exact_path_id}"
            )
        if len(due) != 1:
            raise HealingAuthorityError(
                f"multiple due recovery actions exist for exact path: {exact_path_id}"
            )

        result = self.recovery_orchestrator.execute(
            action_id=str(due[0]["action_id"]),
            owner=owner,
            physical_evidence=tuple(dict(item) for item in physical_evidence),
            active_measurement=dict(active_measurement) if active_measurement is not None else None,
            evidence=dict(evidence or {}),
            observed_at=observed_at,
            now=now,
        )
        result = dict(result)
        result["delegated_to"] = "recovery_orchestrator"
        result["authority_path_id"] = exact_path_id
        return result

    def path(self, path_id: str) -> dict[str, Any]:
        exact_path_id = str(path_id or "").strip()
        if not exact_path_id:
            raise HealingAuthorityError("fabric path id is required")

        physical = next(
            (
                dict(row)
                for row in self.inventory.physical_paths()
                if str(row.get("path_id") or "").strip() == exact_path_id
            ),
            None,
        )
        if physical is None:
            raise HealingAuthorityError(f"unknown physical fabric path: {exact_path_id}")

        intelligence = self.inventory.active_path_intelligence(path_id=exact_path_id)
        recovery_actions = tuple(
            dict(row)
            for row in self.inventory.active_path_recovery_actions(path_id=exact_path_id)
        )

        return {
            "path_id": exact_path_id,
            "physical": physical,
            "active_path": intelligence,
            "recovery_actions": recovery_actions,
            "authorities": self.AUTHORITIES,
        }
