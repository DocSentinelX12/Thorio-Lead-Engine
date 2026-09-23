from __future__ import annotations

import time

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import (
    ComputeRequirements,
    CpuResource,
    GpuRequirements,
    GpuResource,
    NodeResource,
    ResourceState,
    WorkloadClass,
)
from lead_engine.compute_scheduler import ComputeScheduler, ComputeSchedulingError


def _gpu(node: str, gpu_id: str, uuid: str) -> GpuResource:
    return GpuResource(
        node_id=node,
        gpu_id=gpu_id,
        gpu_uuid=uuid,
        vram_bytes=24 * 1024**3,
        compute_capability="8.0",
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )


def _snapshot(tmp_path, *, nodes: tuple[NodeResource, ...], network: dict) -> ComputeInventory:
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(
        ProviderResourceSnapshot(
            provider_id="provider-a",
            domain_id="domain-a",
            observed_at=time.time(),
            nodes=nodes,
            authentication_state="authenticated",
            evidence={"network": network},
        )
    )
    return inventory


def _node(node_id: str, *gpus: GpuResource) -> NodeResource:
    return NodeResource(
        node_id=node_id,
        architecture="x86_64",
        cpu=CpuResource(node_id=node_id, cpu_count=64, memory_bytes=256 * 1024**3),
        gpus=gpus,
        nccl_version="2.20.5",
        state=ResourceState.HEALTHY,
    )


def _network(locality, links, *, domains=None):
    return {
        "source": "verified-test-network",
        "gpu_nic_locality": list(locality),
        "rdma": {
            "devices": [{"device": item["rdma_device"]} for item in locality],
            "links": list(links),
        },
        "network_domains": domains or {},
    }


def _locality(node, gpu, nic, rdma):
    return {
        "node_id": node,
        "gpu_uuid": gpu,
        "nic": nic,
        "rdma_device": rdma,
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }


def _link(rdma):
    return {
        "rdma_device": rdma,
        "port": 1,
        "link_layer": "InfiniBand",
        "state": "ACTIVE",
        "physical_state": "LINK_UP",
    }


def _requirements():
    return ComputeRequirements(
        WorkloadClass.MULTI_GPU,
        GpuRequirements(gpu_count=2, require_nccl=True),
        performance_signature=(
            ("collective", "all_reduce"),
            ("world_size", 2),
            ("message_size_bytes", 1048576),
        ),
    )


def test_complete_placement_rejects_individually_eligible_gpus_with_incomplete_fabric(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [_locality("node-a", "u0", "eth0", "mlx5_0")],
        [_link("mlx5_0")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)

    requirements = ComputeRequirements(
        WorkloadClass.MULTI_GPU,
        GpuRequirements(gpu_count=2, require_nccl=True, min_fabric_bandwidth_gbps=1.0),
        performance_signature=_requirements().performance_signature,
    )
    with pytest.raises(ComputeSchedulingError, match="complete physical placement"):
        scheduler.placement(requirements)


def test_complete_placement_records_verified_physical_evidence(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)

    placement = scheduler.placement(_requirements())

    assert placement.selected_gpu_ids == ("node-a/g0", "node-a/g1")
    assert placement.selected_node_ids == ("node-a",)
    assert placement.evidence["physical_paths"]
    assert placement.evidence["gpu_nic_rdma"]
    assert placement.decision_trace[-1]["stage"] == "stable_resource_ordering"


def test_complete_placement_applies_workload_performance_only_after_physical_validation(tmp_path):
    nodes = (
        _node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),
        _node("node-b", _gpu("node-b", "g0", "u2"), _gpu("node-b", "g1", "u3")),
    )
    locality = [
        _locality("node-a", "u0", "eth0", "mlx5_0"),
        _locality("node-a", "u1", "eth1", "mlx5_1"),
        _locality("node-b", "u2", "eth2", "mlx5_2"),
        _locality("node-b", "u3", "eth3", "mlx5_3"),
    ]
    network = _network(
        locality,
        [_link("mlx5_0"), _link("mlx5_1"), _link("mlx5_2"), _link("mlx5_3")],
        domains={"node-a": ["fabric-a"], "node-b": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)

    def history(requirements=None):
        return {}

    scheduler = ComputeScheduler(inventory, performance_history_provider=history)
    placement = scheduler.placement(_requirements())

    assert placement.selected_node_ids == ("node-a",)
    assert placement.selected_gpu_ids == ("node-a/g0", "node-a/g1")
    assert any(item["stage"] == "workload_performance" for item in placement.decision_trace)


def test_equivalent_complete_candidates_have_stable_ordering(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)

    first = scheduler.placement(_requirements())
    second = scheduler.placement(_requirements())

    assert first.placement_id == second.placement_id
    assert first.decision_trace == second.decision_trace


def test_allocate_uses_complete_physical_placement_gate(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [_locality("node-a", "u0", "eth0", "mlx5_0")],
        [_link("mlx5_0")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)

    requirements = ComputeRequirements(
        WorkloadClass.MULTI_GPU,
        GpuRequirements(
            gpu_count=2,
            require_nccl=True,
            min_fabric_bandwidth_gbps=1.0,
        ),
        performance_signature=_requirements().performance_signature,
    )
    with pytest.raises(ComputeSchedulingError, match="complete physical placement"):
        scheduler.allocate(requirements, "invalid-placement")


def test_multi_node_placement_requires_verified_shared_fabric_domain(tmp_path):
    nodes = (
        _node("node-a", _gpu("node-a", "g0", "u0")),
        _node("node-b", _gpu("node-b", "g0", "u1")),
    )
    locality = [
        _locality("node-a", "u0", "eth0", "mlx5_0"),
        _locality("node-b", "u1", "eth1", "mlx5_1"),
    ]
    network = _network(
        locality,
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"], "node-b": ["fabric-b"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)
    requirements = ComputeRequirements(
        WorkloadClass.MULTI_NODE_GPU,
        GpuRequirements(gpu_count=2, require_nccl=True),
        same_node=False,
    )

    with pytest.raises(ComputeSchedulingError, match="complete physical placement"):
        scheduler.placement(requirements)


def test_placement_evidence_retains_rejection_reason(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [_locality("node-a", "u0", "eth0", "mlx5_0")],
        [_link("mlx5_0")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)

    requirements = ComputeRequirements(
        WorkloadClass.MULTI_GPU,
        GpuRequirements(gpu_count=2, require_nccl=True, min_fabric_bandwidth_gbps=1.0),
        performance_signature=_requirements().performance_signature,
    )
    with pytest.raises(ComputeSchedulingError):
        scheduler.placement(requirements)

    assert any(
        item["status"] == "rejected"
        and item["stage"] == "complete_communication_path_validity"
        for item in scheduler._last_placement_trace
    )


def test_successful_placement_persists_candidate_evaluations_and_requirements(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)
    placement = scheduler.placement(_requirements())

    assert placement.evidence["candidate_evaluations"]
    assert placement.evidence["rejection_count"] == 0
    assert placement.evidence["candidate_evaluations"][0]["status"] == "accepted"


def test_placement_identity_includes_stable_workload_constraints(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)

    first = scheduler.placement(_requirements())
    constrained = ComputeRequirements(
        WorkloadClass.MULTI_GPU,
        GpuRequirements(gpu_count=2, min_vram_bytes=24 * 1024**3, require_nccl=True),
        performance_signature=_requirements().performance_signature,
    )
    second = scheduler.placement(constrained)

    assert first.selected_resource_keys == second.selected_resource_keys
    assert first.placement_id != second.placement_id


def test_placement_can_be_persisted_and_retrieved_without_mutating_allocation(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)
    placement = scheduler.placement(_requirements())

    stored = inventory.persist_placement(placement)

    assert stored["placement_id"] == placement.placement_id
    assert inventory.placement(placement.placement_id)["selected_gpu_ids"] == list(placement.selected_gpu_ids)
    assert inventory.allocations() == []


def test_persisted_placement_identity_is_idempotent(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    placement = ComputeScheduler(inventory).placement(_requirements())

    first = inventory.persist_placement(placement)
    second = inventory.persist_placement(placement)

    assert first == second
    assert len(inventory.placements()) == 1


def test_allocation_can_reference_placement_without_creating_second_reservation(tmp_path):
    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    scheduler = ComputeScheduler(inventory)
    placement = scheduler.placement(_requirements())
    inventory.persist_placement(placement)

    allocation = scheduler.allocate(_requirements(), "placement-allocation")

    assert allocation.capability_evidence
    assert inventory.placement(placement.placement_id)["placement_id"] == placement.placement_id
    assert len(inventory.allocations(state="reserved")) == 1


def test_claimed_execution_attempt_retains_placement_identity(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator

    nodes = (_node("node-a", _gpu("node-a", "g0", "u0"), _gpu("node-a", "g1", "u1")),)
    network = _network(
        [
            _locality("node-a", "u0", "eth0", "mlx5_0"),
            _locality("node-a", "u1", "eth1", "mlx5_1"),
        ],
        [_link("mlx5_0"), _link("mlx5_1")],
        domains={"node-a": ["fabric-a"]},
    )
    inventory = _snapshot(tmp_path, nodes=nodes, network=network)
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        "test-token",
        inventory=inventory,
    )
    coordinator.enqueue(
        {
            "compute_requirements": {
                "workload_class": "multi_gpu",
                "gpu": {"gpu_count": 2, "require_nccl": True},
                "min_cpu_count": 1,
                "min_memory_bytes": 1,
                "same_node": True,
            }
        },
        task_id="placement-task",
    )

    claimed = coordinator.claim_physical()

    assert claimed is not None
    attempt = coordinator.execution_attempt(claimed["attempt_id"])
    assert attempt["placement_id"]
    assert inventory.placement(attempt["placement_id"]) is not None
