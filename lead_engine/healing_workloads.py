"""Execution-state-preserving workload healing."""

from __future__ import annotations

from typing import Any


class WorkloadRecoveryError(RuntimeError):
    pass


class WorkloadRecoveryPlanner:
    def __init__(self):
        self._effects: set[tuple[str, str]] = set()

    def plan_restart(self, *, workload_id: str, execution_id: str,
                     checkpoint_id: str | None, original_scope: str) -> dict[str, Any]:
        if not workload_id.strip() or not execution_id.strip() or not original_scope.strip():
            raise ValueError("workload_id, execution_id, and original_scope are required")
        return {
            "action": "restart",
            "workload_id": workload_id,
            "execution_id": execution_id,
            "checkpoint_id": checkpoint_id,
            "original_scope": original_scope,
        }

    def plan_migration(self, *, workload_id: str, execution_id: str,
                       destination: dict[str, Any]) -> dict[str, Any]:
        if destination.get("allocation_authoritative") is not True or destination.get("capacity_verified") is not True:
            raise WorkloadRecoveryError("authoritative destination capacity is required")
        path_id = str(destination.get("fabric_path_id") or "").strip()
        if not path_id or destination.get("fabric_path_verified") is not True:
            raise WorkloadRecoveryError("exact verified fabric path is required")
        if not workload_id.strip() or not execution_id.strip():
            raise ValueError("workload_id and execution_id are required")
        return {
            "action": "migrate",
            "workload_id": workload_id,
            "execution_id": execution_id,
            "fabric_path_id": path_id,
        }

    def record_effect(self, workload_id: str, effect_id: str) -> bool:
        key = (workload_id, effect_id)
        if key in self._effects:
            return False
        self._effects.add(key)
        return True
