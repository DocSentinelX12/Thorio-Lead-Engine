from __future__ import annotations

import pytest

from lead_engine.healing_workloads import WorkloadRecoveryPlanner, WorkloadRecoveryError


def test_workload_restart_preserves_execution_identity():
    planner = WorkloadRecoveryPlanner()
    result = planner.plan_restart(
        workload_id="w1", execution_id="exec-7", checkpoint_id="ckpt-7",
        original_scope="node-a",
    )
    assert result["action"] == "restart"
    assert result["execution_id"] == "exec-7"
    assert result["checkpoint_id"] == "ckpt-7"


def test_workload_migration_requires_authoritative_capacity_and_exact_verified_path():
    planner = WorkloadRecoveryPlanner()
    result = planner.plan_migration(
        workload_id="w2", execution_id="exec-8", destination={
            "allocation_authoritative": True,
            "capacity_verified": True,
            "fabric_path_id": "path-8",
            "fabric_path_verified": True,
        },
    )
    assert result["action"] == "migrate"
    assert result["fabric_path_id"] == "path-8"


def test_workload_migration_rejects_missing_path_or_capacity():
    planner = WorkloadRecoveryPlanner()
    with pytest.raises(WorkloadRecoveryError, match="exact verified fabric path"):
        planner.plan_migration(
            workload_id="w3", execution_id="exec-9",
            destination={"allocation_authoritative": True, "capacity_verified": True},
        )
    with pytest.raises(WorkloadRecoveryError, match="authoritative destination capacity"):
        planner.plan_migration(
            workload_id="w3", execution_id="exec-9",
            destination={"fabric_path_id": "p", "fabric_path_verified": True},
        )


def test_workload_recovery_avoids_duplicate_side_effects():
    planner = WorkloadRecoveryPlanner()
    first = planner.record_effect("w4", "effect-1")
    second = planner.record_effect("w4", "effect-1")
    assert first is True
    assert second is False
