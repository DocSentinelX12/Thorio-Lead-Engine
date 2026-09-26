"""Final branch-level 12-supercomputer chaos proof.

This is deliberately an integration proof, not another isolated component suite.
It drives the durable inventory, exact physical-path recovery, active measurement,
global placement, workload identity, controller fencing, replicated healing state,
learning, closure, restart reconciliation, and concurrent recovery together.
"""
from __future__ import annotations

import json

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
from lead_engine.continuous_recovery import ContinuousRecoveryController, ContinuousRecoveryError
from lead_engine.healing_closure import HealingClosureValidator
from lead_engine.healing_control_plane import ControlPlaneRecovery
from lead_engine.healing_learning import HealingLearning
from lead_engine.healing_replication import ReplicatedHealingState
from lead_engine.healing_authorities import HealingIntegrationFabric
from lead_engine.healing_workloads import WorkloadRecoveryPlanner
from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
from lead_engine.recovery_orchestrator import RecoveryOrchestrator
from lead_engine.self_coordinating_fabric import FabricCoordinator, NodeCapacity, PlacementCandidate


SUPERCOMPUTERS = 12
WORKLOADS = 12


def _snapshot(supercomputer: int) -> ProviderResourceSnapshot:
    provider = f"final-sc-{supercomputer:02d}"
    domain = f"final-domain-{supercomputer:02d}"
    node_id = f"{provider}-node-00"
    gpus = tuple(
        GpuResource(
            node_id=node_id,
            gpu_id=f"gpu-{gpu_index:02d}",
            gpu_uuid=f"{provider}-uuid-{gpu_index:02d}",
            model="NVIDIA H100",
            vram_bytes=80 * 1024**3,
            compute_capability="9.0",
            driver_version="550.54.15",
            cuda_version="12.4",
            numa_node=gpu_index,
            topology_domain=f"{provider}-topology",
            health_state=ResourceState.HEALTHY,
            availability_state=ResourceState.AVAILABLE,
        )
        for gpu_index in range(2)
    )
    return ProviderResourceSnapshot(
        provider_id=provider,
        domain_id=domain,
        observed_at=100.0,
        nodes=(
            NodeResource(
                node_id=node_id,
                architecture="x86_64",
                cpu=CpuResource(node_id, 128, 512 * 1024**3),
                gpus=gpus,
                driver_version="550.54.15",
                cuda_version="12.4",
                nccl_version="2.21",
                state=ResourceState.AVAILABLE,
            ),
        ),
        authentication_state="authenticated",
        evidence={"source": "final_12_supercomputer_chaos_proof"},
    )


def _path(path_id: str, domain: str) -> PhysicalFabricPath:
    return PhysicalFabricPath(
        path_id=path_id,
        source_gpu=f"gpu:{path_id}:source",
        destination_gpu=f"gpu:{path_id}:destination",
        segments=(f"gpu:{path_id}:source", f"rdma:{path_id}:1"),
        fabric_domains=(domain,),
        state=FabricPathState.VERIFIED,
    )


def _measurement(path_id: str, observed_at: float, bandwidth: float = 100.0) -> dict[str, object]:
    return {
        "fabric_path_id": path_id,
        "measurement_status": "measured",
        "verified": True,
        "remote_test_server_verified": True,
        "worker_id": f"worker:{path_id}",
        "remote_worker_id": f"remote:{path_id}",
        "remote_endpoint": f"endpoint:{path_id}",
        "gpu_uuid": f"{path_id}:gpu",
        "rdma_device": f"rdma:{path_id}",
        "rdma_port": 1,
        "bandwidth_gbps": bandwidth,
        "observed_at": observed_at,
    }


def _integration(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = FabricCoordinator(str(tmp_path / "coordinator.sqlite3"), standby_capacity=2)
    control = ControlPlaneRecovery(str(tmp_path / "control.sqlite3"))
    return HealingIntegrationFabric(
        inventory=inventory,
        recovery_orchestrator=RecoveryOrchestrator(inventory),
        fabric_coordinator=coordinator,
        workload_recovery=WorkloadRecoveryPlanner(),
        control_plane=control,
        learning=HealingLearning(str(tmp_path / "learning.sqlite3")),
        closure=HealingClosureValidator(),
    )


def _prepare_fabric(integration: HealingIntegrationFabric) -> tuple[dict[str, PhysicalFabricPath], dict[str, str]]:
    gpu_keys: dict[str, str] = {}
    for index in range(SUPERCOMPUTERS):
        integration.inventory.observe(_snapshot(index))
        node_id = f"final-sc-{index:02d}-node-00"
        gpu = next(
            item for item in integration.inventory.resources()
            if item["node_id"] == node_id and item["resource_type"] == "gpu"
        )
        gpu_keys[node_id] = str(gpu["resource_key"])

    paths: dict[str, PhysicalFabricPath] = {}
    for index in range(SUPERCOMPUTERS):
        path_id = f"final-path-{index:02d}"
        path = _path(path_id, f"final-domain-{index:02d}")
        integration.inventory.persist_physical_path(path)
        integration.inventory.record_active_gdrdma_measurement(
            path_id=path_id, measurement=_measurement(path_id, 10.0)
        )
        integration.inventory.record_active_gdrdma_measurement(
            path_id=path_id, measurement=_measurement(path_id, 11.0)
        )
        paths[path_id] = path

    replacement = _path("final-replacement-00", "final-standby-domain-00")
    integration.inventory.persist_physical_path(replacement)
    integration.inventory.record_active_gdrdma_measurement(
        path_id=replacement.path_id, measurement=_measurement(replacement.path_id, 12.0)
    )
    integration.inventory.record_active_gdrdma_measurement(
        path_id=replacement.path_id, measurement=_measurement(replacement.path_id, 13.0)
    )
    paths[replacement.path_id] = replacement
    return paths, gpu_keys


def _prepare_competing_workloads(integration: HealingIntegrationFabric) -> dict[str, dict[str, object]]:
    candidates: list[PlacementCandidate] = []
    expected: dict[str, dict[str, object]] = {}
    for index in range(WORKLOADS):
        node = f"final-sc-{index:02d}-node-00"
        workload = f"workload-{index:02d}"
        path_id = f"final-path-{index:02d}"
        domain = f"final-domain-{index:02d}"
        integration.fabric_coordinator.register_node(NodeCapacity(node, domain, 1, 1, 1))
        integration.fabric_coordinator.submit_workload(workload, criticality=3 if index < 4 else 2)
        candidates.append(PlacementCandidate(workload, node, domain, path_id, 100.0 - index))
        expected[workload] = {"node_id": node, "path_id": path_id, "generation": 1}

    integration.fabric_coordinator.register_node(NodeCapacity("final-standby-00", "final-standby-domain-00", 1, 1, 1))
    integration.fabric_coordinator.register_node(NodeCapacity("final-standby-01", "final-standby-domain-01", 1, 1, 1))

    result = integration.coordinate(candidates)
    assert len(result["allocations"]) == WORKLOADS
    assert len({item["workload_id"] for item in result["allocations"]}) == WORKLOADS
    assert len({item["node_id"] for item in result["allocations"]}) == WORKLOADS
    assert len(result["standby_node_ids"]) == 2
    return expected


def _evidence(action):
    path_id = str(action["path_id"])
    required_segments = tuple(action["trigger_snapshot"]["required_segments"])
    return {
        "physical_evidence": tuple({"segment": segment, "result": "pass"} for segment in required_segments),
        "active_measurement": _measurement(path_id, float(action["updated_at"]) + 1.0),
        "evidence": {
            "proof_phase": "authoritative_recovery",
            "fabric_path_id": path_id,
        },
        "observed_at": float(action["updated_at"]) + 1.0,
    }


def _run_recovery(controller: ContinuousRecoveryController, *, now: float):
    return controller.run_cycle(evidence_provider=_evidence, now=now)


def test_final_12_supercomputer_system_proof_survives_two_failures_restart_and_reconciliation(tmp_path):
    integration = _integration(tmp_path)
    paths, gpu_keys = _prepare_fabric(integration)
    expected = _prepare_competing_workloads(integration)

    # Normal operation and exact-path identity are established before chaos.
    initial = integration.fabric_coordinator.snapshot()
    assert {row["workload_id"] for row in initial["allocations"]} == set(expected)
    assert all(row["state"] == "active" for row in initial["allocations"])
    assert all(row["fabric_path_id"] in paths for row in initial["allocations"])

    # Failure one: two independent failure domains must remain concurrently recoverable.
    for path_id in ("final-path-00", "final-path-01"):
        integration.inventory.fail_physical_path(
            path_id, reason="controlled chaos failure", observed_at=20.0,
            evidence={"failure_domain": paths[path_id].fabric_domains[0]},
        )

    controller_db = str(tmp_path / "continuous.sqlite3")
    controller_a = ContinuousRecoveryController(
        gateway=integration.gateway, db_path=controller_db, controller_id="controller-a"
    )
    controller_a.start(generation=1, now=21.0, lease_seconds=5.0)

    for path_id in ("final-path-00", "final-path-01"):
        controller_a.observe(
            path_id=path_id, generation=1, fingerprint=f"failure-{path_id}",
            criticality=3, confidence=0.99, cascade_risk=0.05, now=22.0,
        )

    scheduled = controller_a.schedule(now=23.0)
    assert len(scheduled) == 2
    assert {episode["mode"] for episode in scheduled} == {"PARALLEL_INDEPENDENT"}

    first_results = _run_recovery(controller_a, now=24.0)
    assert len(first_results) == 2
    assert {result["path_id"] for result in first_results} == {"final-path-00", "final-path-01"}
    assert all(result["state"] == "SUCCEEDED" for result in first_results)
    assert all(result["allow_routing"] is True for result in first_results)
    assert all(result["authority_path_id"] == result["path_id"] for result in first_results)
    assert all("test_id" in result for result in first_results)

    for path_id in ("final-path-00", "final-path-01"):
        physical = integration.inventory.physical_paths()
        record = next(item for item in physical if item["path_id"] == path_id)
        assert record["state"] == "MEASURED"
        assert integration.inventory.active_path_intelligence(path_id=path_id)["state"] == "stable"
        closed = integration.close_recovery(
            path_id=path_id,
            authoritative_verified=True,
            healing_verified=True,
            secondary_damage=False,
            strategy="known-good-exact-path-recovery",
            success=True,
            evidence={"observed_at": 24.0, "experiment": "final-chaos-proof"},
        )
        assert closed["state"] == "CLOSED"

    # Protect failed hardware from being silently returned to the healthy pool.
    failed_gpu = gpu_keys["final-sc-00-node-00"]
    assert integration.inventory.mark_state(failed_gpu, ResourceState.QUARANTINED)
    fleet = integration.inventory.fleet_resource_intelligence(now=25.0)
    assert fleet["totals"]["gpu"]["QUARANTINED"] >= 1
    assert fleet["totals"]["gpu"]["AVAILABLE"] < fleet["totals"]["gpu"]["TOTAL"]

    # A third failure is intentionally left unfinished, then the controller restarts.
    integration.inventory.fail_physical_path(
        "final-path-02", reason="second-wave controlled failure", observed_at=30.0,
        evidence={"failure_domain": "final-domain-02"},
    )
    controller_a.observe(
        path_id="final-path-02", generation=1, fingerprint="failure-final-path-02",
        criticality=3, confidence=0.99, cascade_risk=0.05, now=31.0,
    )
    controller_a.schedule(now=31.5)

    controller_b = ContinuousRecoveryController(
        gateway=integration.gateway, db_path=controller_db, controller_id="controller-b"
    )
    controller_b.start(generation=2, now=32.0)
    reconciled = controller_b.reconcile(now=33.0)
    assert reconciled
    assert reconciled[0]["scope_id"] == "final-path-02"
    assert reconciled[0]["state"] == "RETRY"

    with pytest.raises(ContinuousRecoveryError, match="stale, fenced, or lease expired"):
        controller_a.observe(
            path_id="final-path-03", generation=1, fingerprint="stale-controller",
            criticality=2, confidence=0.9, cascade_risk=0.1, now=34.0,
        )

    second_results = _run_recovery(controller_b, now=35.0)
    assert any(
        result["path_id"] == "final-path-02"
        and result["state"] == "SUCCEEDED"
        and result["allow_routing"] is True
        for result in second_results
    )

    # A fresh independent failure after restart proves the new controller can
    # continue concurrent recovery rather than merely reconciling old state.
    integration.inventory.fail_physical_path(
        "final-path-03", reason="post-restart independent failure", observed_at=40.0,
        evidence={"failure_domain": "final-domain-03"},
    )
    controller_b.observe(
        path_id="final-path-03", generation=2, fingerprint="failure-final-path-03",
        criticality=3, confidence=0.99, cascade_risk=0.05, now=41.0,
    )
    third_results = _run_recovery(controller_b, now=42.0)
    assert any(
        result["path_id"] == "final-path-03"
        and result["state"] == "SUCCEEDED"
        and result["allow_routing"] is True
        for result in third_results
    )

    # Replanning after a node failure preserves workload identity and avoids the
    # failed node and failed path. The replacement path is already physically known.
    migration_candidates = [
        PlacementCandidate(
            "workload-00", "final-standby-00", "final-standby-domain-00",
            "final-replacement-00", 99.0
        )
    ]
    migration = integration.fabric_coordinator.reconcile_node_failure(
        "final-sc-00-node-00", candidates=migration_candidates
    )
    assert len(migration["migrated"]) == 1
    moved = migration["migrated"][0]
    assert moved["workload_id"] == "workload-00"
    assert moved["node_id"] == "final-standby-00"
    assert moved["fabric_path_id"] == "final-replacement-00"
    assert moved["fabric_path_id"] != "final-path-00"

    plan = integration.plan_migration(
        workload_id="workload-00",
        execution_id="final-exec-00",
        allocation=moved,
        path_verified=True,
    )
    assert plan["action"] == "migrate"
    assert plan["workload_id"] == "workload-00"
    assert plan["fabric_path_id"] == "final-replacement-00"

    # Controller fencing is also proven through the replicated authoritative state.
    replicated = ReplicatedHealingState(
        tuple(str(tmp_path / f"replica-{index}.sqlite3") for index in range(3))
    )
    control = ControlPlaneRecovery(
        str(tmp_path / "replicated-control.sqlite3"), replicated_state=replicated
    )
    first = control.register("controller-a", generation=1)
    takeover = control.takeover("controller-b", generation=2)
    assert takeover["fencing_token"] > first["fencing_token"]
    with pytest.raises(Exception, match="fenced"):
        control.reconcile("controller-a", generation=1, authoritative_state={})
    control.reconcile(
        "controller-b",
        generation=2,
        authoritative_state={
            "failed_paths": ["final-path-00", "final-path-01", "final-path-02", "final-path-03"],
            "active_allocations": integration.fabric_coordinator.snapshot()["allocations"],
        },
    )
    active_control = control.activate("controller-b", generation=2)
    assert active_control["state"] == "ACTIVE"

    # Restart the durable inventory and prove that physical truth, path identity,
    # recovery actions, and allocation truth are still convergent and exact.
    reopened = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    for path_id in ("final-path-00", "final-path-01", "final-path-02", "final-path-03"):
        record = next(item for item in reopened.physical_paths() if item["path_id"] == path_id)
        assert record["state"] == "MEASURED"
        assert record["path_id"] == path_id
        assert reopened.active_path_intelligence(path_id=path_id)["state"] == "stable"

    final_coord = integration.fabric_coordinator.snapshot()
    active_allocations = final_coord["allocations"]
    assert len({row["workload_id"] for row in active_allocations}) == len(active_allocations)
    assert len({row["node_id"] for row in active_allocations}) == len(active_allocations)
    assert all(row["fabric_path_id"] != "final-path-00" for row in active_allocations)
    assert all(row["node_id"] != "final-sc-00-node-00" for row in active_allocations)
    assert {row["workload_id"] for row in active_allocations} == set(expected)

    episodes = controller_b.snapshot()["episodes"]
    assert all(
        episode["state"] == "RECOVERED"
        for episode in episodes
        if episode["scope_id"] in {"final-path-00", "final-path-01", "final-path-02", "final-path-03"}
    )
    assert active_control["reconciled"] == 1


def test_final_proof_rejects_stale_recovery_and_preserves_authoritative_gates(tmp_path):
    integration = _integration(tmp_path)
    paths, _ = _prepare_fabric(integration)

    integration.inventory.fail_physical_path(
        "final-path-04", reason="stale-generation proof", observed_at=50.0,
        evidence={"failure_domain": "final-domain-04"},
    )
    action = next(
        item for item in integration.recovery_orchestrator.discover(now=51.0)
        if item["path_id"] == "final-path-04"
    )
    assert action["path_id"] == "final-path-04"

    # Change the authoritative trigger after the durable action was created.
    integration.inventory.fail_physical_path(
        "final-path-04", reason="newer-authoritative-trigger", observed_at=52.0,
        evidence={"failure_domain": "final-domain-04", "generation": "new"},
    )
    stale = integration.recovery_orchestrator.execute(
        action_id=action["action_id"],
        owner="stale-proof",
        physical_evidence=tuple({"segment": segment, "result": "pass"} for segment in paths["final-path-04"].segments),
        active_measurement=_measurement("final-path-04", 53.0),
        observed_at=53.0,
        now=53.0,
    )
    assert stale["state"] == "CANCELLED"
    assert stale["allow_routing"] is False
    assert next(
        item for item in integration.inventory.physical_paths()
        if item["path_id"] == "final-path-04"
    )["state"] == "FAILED"


def test_final_proof_preserves_protected_standby_capacity(tmp_path):
    integration = _integration(tmp_path)
    _prepare_fabric(integration)
    _prepare_competing_workloads(integration)

    snapshot = integration.fabric_coordinator.snapshot()
    standby = {
        node["node_id"]
        for node in snapshot["nodes"]
        if node["node_id"].startswith("final-standby-")
        and node["state"] == "available"
    }
    assert standby == {"final-standby-00", "final-standby-01"}

    assert integration.fabric_coordinator.can_experiment(required_nodes=1) is False
