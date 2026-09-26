from __future__ import annotations

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.healing_authorities import HealingAuthorityError, HealingIntegrationFabric
from lead_engine.healing_closure import HealingClosureValidator
from lead_engine.healing_control_plane import ControlPlaneRecovery
from lead_engine.healing_learning import HealingLearning
from lead_engine.healing_workloads import WorkloadRecoveryPlanner
from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
from lead_engine.recovery_orchestrator import RecoveryOrchestrator
from lead_engine.self_coordinating_fabric import FabricCoordinator, NodeCapacity, PlacementCandidate


def _path(path_id: str) -> PhysicalFabricPath:
    return PhysicalFabricPath(
        path_id=path_id,
        source_gpu=f"gpu:{path_id}:a",
        destination_gpu=f"gpu:{path_id}:b",
        segments=(f"gpu:{path_id}:a", f"rdma:{path_id}:1"),
        fabric_domains=(f"domain:{path_id}",),
        state=FabricPathState.VERIFIED,
    )


def _measurement(path_id: str, observed_at: float, bandwidth: float) -> dict[str, object]:
    return {
        "fabric_path_id": path_id,
        "measurement_status": "measured",
        "verified": True,
        "remote_test_server_verified": True,
        "worker_id": f"worker:{path_id}",
        "remote_worker_id": f"remote:{path_id}",
        "remote_endpoint": f"endpoint:{path_id}",
        "gpu_uuid": f"{path_id}:a",
        "rdma_device": path_id,
        "rdma_port": 1,
        "bandwidth_gbps": bandwidth,
    }


def _integration(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    orchestrator = RecoveryOrchestrator(inventory)
    coordinator = FabricCoordinator(str(tmp_path / "coord.sqlite3"), standby_capacity=1)
    workloads = WorkloadRecoveryPlanner()
    control = ControlPlaneRecovery(str(tmp_path / "control.sqlite3"))
    learning = HealingLearning(str(tmp_path / "learning.sqlite3"))
    closure = HealingClosureValidator()
    return HealingIntegrationFabric(
        inventory=inventory,
        recovery_orchestrator=orchestrator,
        fabric_coordinator=coordinator,
        workload_recovery=workloads,
        control_plane=control,
        learning=learning,
        closure=closure,
    )


def test_full_exact_path_recovery_closes_and_records_learning(tmp_path):
    integration = _integration(tmp_path)
    path = _path("path-integrated")
    integration.inventory.persist_physical_path(path)
    integration.inventory.record_active_gdrdma_measurement(
        path_id=path.path_id, measurement=_measurement(path.path_id, 1.0, 200.0)
    )
    integration.inventory.record_active_gdrdma_measurement(
        path_id=path.path_id, measurement=_measurement(path.path_id, 2.0, 198.0)
    )
    integration.inventory.fail_physical_path(path.path_id, reason="link failure", observed_at=3.0)

    result = integration.recover_path(
        path_id=path.path_id,
        owner="healer",
        physical_evidence=tuple({"segment": segment, "result": "pass"} for segment in path.segments),
        active_measurement=_measurement(path.path_id, 4.0, 199.0),
        observed_at=4.0,
        now=4.0,
    )

    assert result["state"] == "SUCCEEDED"
    assert result["allow_routing"] is True
    assert result["authority_path_id"] == path.path_id
    closed = integration.close_recovery(
        path_id=path.path_id,
        authoritative_verified=True,
        healing_verified=True,
        secondary_damage=False,
        strategy="known-good-exact-path-recovery",
        success=True,
        evidence={"recovery_state": result["state"]},
    )
    assert closed["state"] == "CLOSED"
    assert closed["learning"]["successes"] == 1


def test_placement_and_migration_use_authoritative_allocation_and_exact_path(tmp_path):
    integration = _integration(tmp_path)
    integration.fabric_coordinator.register_node(NodeCapacity("node-a", "domain-a", 8, 8, 8))
    integration.fabric_coordinator.register_node(NodeCapacity("node-b", "domain-b", 8, 8, 8))
    integration.fabric_coordinator.submit_workload("workload-a", criticality=3)
    path = _path("path-a")
    integration.inventory.persist_physical_path(path)
    allocation = integration.coordinate(
        (
            PlacementCandidate("workload-a", "node-a", "domain-a", "path-a", 10.0),
        )
    )
    record = allocation["allocations"][0]

    plan = integration.plan_migration(
        workload_id="workload-a",
        execution_id="exec-a",
        allocation=record,
        path_verified=True,
    )
    assert plan["fabric_path_id"] == "path-a"
    assert plan["action"] == "migrate"


def test_migration_rejects_non_authoritative_or_unverified_path(tmp_path):
    integration = _integration(tmp_path)
    with pytest.raises(HealingAuthorityError):
        integration.plan_migration(
            workload_id="workload-a",
            execution_id="exec-a",
            allocation={
                "allocation_authoritative": True,
                "capacity_verified": True,
                "fabric_path_id": "path-a",
            },
            path_verified=False,
        )


def test_control_plane_recovery_requires_authoritative_reconciliation(tmp_path):
    integration = _integration(tmp_path)
    integration.control_plane.register("controller-a", generation=1)
    takeover = integration.takeover_control_plane("controller-b", generation=2)
    assert takeover["state"] == "FENCED_PENDING_RECONCILIATION"
    with pytest.raises(Exception):
        integration.activate_control_plane("controller-b", generation=2)
    integration.reconcile_control_plane(
        "controller-b", generation=2, authoritative_state={"allocations": [], "paths": []}
    )
    active = integration.activate_control_plane("controller-b", generation=2)
    assert active["state"] == "ACTIVE"
    assert active["fencing_token"] == takeover["fencing_token"]


def test_integration_never_invents_unknown_physical_path(tmp_path):
    integration = _integration(tmp_path)
    with pytest.raises(HealingAuthorityError, match="unknown physical fabric path"):
        integration.path_evidence("not-real")


def test_recovery_closure_does_not_promote_before_evidence(tmp_path):
    integration = _integration(tmp_path)
    with pytest.raises(HealingAuthorityError):
        integration.close_recovery(
            path_id="path-x",
            authoritative_verified=False,
            healing_verified=True,
            secondary_damage=False,
            strategy="experimental",
            success=True,
            evidence={},
            promote=True,
        )
