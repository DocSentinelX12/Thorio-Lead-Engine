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
from lead_engine.physical_fabric import PhysicalFabricPathBuilder, PhysicalFabricVerification


def _gpu(node: str, gpu_id: str, uuid: str) -> GpuResource:
    return GpuResource(
        node_id=node, gpu_id=gpu_id, gpu_uuid=uuid, vram_bytes=24 * 1024**3,
        compute_capability="8.0", health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )


def _node(node_id: str, gpu: GpuResource) -> NodeResource:
    return NodeResource(
        node_id=node_id, architecture="x86_64",
        cpu=CpuResource(node_id=node_id, cpu_count=64, memory_bytes=256 * 1024**3),
        gpus=(gpu,), nccl_version="2.20.5", state=ResourceState.HEALTHY,
    )


def _network() -> dict:
    locality = [
        {"node_id": "node-a", "gpu_uuid": "u0", "nic": "eth0", "rdma_device": "mlx5_0", "rdma_port": 1, "link_layer": "InfiniBand"},
        {"node_id": "node-b", "gpu_uuid": "u1", "nic": "eth1", "rdma_device": "mlx5_1", "rdma_port": 1, "link_layer": "InfiniBand"},
    ]
    links = [
        {"rdma_device": "mlx5_0", "port": 1, "link_layer": "InfiniBand", "state": "ACTIVE", "physical_state": "LINK_UP"},
        {"rdma_device": "mlx5_1", "port": 1, "link_layer": "InfiniBand", "state": "ACTIVE", "physical_state": "LINK_UP"},
    ]
    return {
        "source": "integration-test",
        "gpu_nic_locality": locality,
        "rdma": {"devices": [{"device": "mlx5_0"}, {"device": "mlx5_1"}], "links": links},
        "network_domains": {"node-a": ["fabric-a"], "node-b": ["fabric-a"]},
    }


def _requirements() -> ComputeRequirements:
    return ComputeRequirements(
        WorkloadClass.MULTI_NODE_GPU,
        GpuRequirements(gpu_count=2, require_nccl=True),
        same_node=False,
        performance_signature=(("collective", "all_reduce"), ("world_size", 2)),
    )


def _concrete_path() -> object:
    components = [
        {"component_type": "gpu", "identity": "gpu:u0", "node_id": "node-a"},
        {"component_type": "pci", "identity": "pci:src", "node_id": "node-a"},
        {"component_type": "numa", "identity": "numa:src", "node_id": "node-a"},
        {"component_type": "nic", "identity": "nic:src", "node_id": "node-a"},
        {"component_type": "rdma_device", "identity": "rdma:src", "node_id": "node-a"},
        {"component_type": "rdma_port", "identity": "rdma:src:1", "node_id": "node-a"},
        {"component_type": "fabric", "identity": "fabric:ib0", "node_id": "domain-1"},
        {"component_type": "rdma_port", "identity": "rdma:dst:1", "node_id": "node-b"},
        {"component_type": "rdma_device", "identity": "rdma:dst", "node_id": "node-b"},
        {"component_type": "nic", "identity": "nic:dst", "node_id": "node-b"},
        {"component_type": "numa", "identity": "numa:dst", "node_id": "node-b"},
        {"component_type": "pci", "identity": "pci:dst", "node_id": "node-b"},
        {"component_type": "gpu", "identity": "gpu:u1", "node_id": "node-b"},
    ]
    def rel(kind: str, source: str, target: str) -> dict[str, object]:
        return {"relationship_type": kind, "source": source, "target": target, "state": "known", "evidence": {"source": "probe"}}
    edges = [
        rel("gpu_to_pci", "gpu:u0", "pci:src"), rel("gpu_to_numa", "gpu:u0", "numa:src"),
        rel("gpu_to_nic", "gpu:u0", "nic:src"), rel("nic_to_pci", "nic:src", "pci:src"),
        rel("nic_to_rdma_device", "nic:src", "rdma:src"), rel("rdma_device_to_port", "rdma:src", "rdma:src:1"),
        rel("rdma_port_to_fabric", "rdma:src:1", "fabric:ib0"), rel("fabric_to_rdma_port", "fabric:ib0", "rdma:dst:1"),
        rel("rdma_device_to_port", "rdma:dst", "rdma:dst:1"), rel("nic_to_rdma_device", "nic:dst", "rdma:dst"),
        rel("nic_to_pci", "nic:dst", "pci:dst"), rel("gpu_to_nic", "gpu:u1", "nic:dst"),
        rel("gpu_to_numa", "gpu:u1", "numa:dst"), rel("gpu_to_pci", "gpu:u1", "pci:dst"),
    ]
    path = PhysicalFabricPathBuilder.build(
        locality_graph={"components": components, "edges": edges},
        source_gpu="gpu:u0", destination_gpu="gpu:u1",
    )[0]
    verification = PhysicalFabricVerification.verify(
        path,
        evidence=[{"segment": s, "operation": "probe", "result": "pass"} for s in path.segments],
    )
    assert verification.state.value == "VERIFIED"
    return path


def test_execution_metric_is_bound_to_concrete_path_id_and_placement_id(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = _concrete_path()
    inventory.persist_physical_path(path)
    verification = PhysicalFabricVerification.verify(
        path, evidence=[{"segment": s, "operation": "probe", "result": "pass"} for s in path.segments]
    )
    inventory.persist_physical_verification(verification, evidence={"stage": "path_verification"})
    record = inventory.physical_paths()[0]
    assert record["path_id"] == path.path_id
    assert record["state"] == "VERIFIED"
    assert inventory.physical_verification_history()[0]["path_id"] == path.path_id


def test_multi_node_placement_requires_verified_concrete_path(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(
        ProviderResourceSnapshot(
            provider_id="provider-a", domain_id="domain-a", observed_at=time.time(),
            nodes=(_node("node-a", _gpu("node-a", "g0", "u0")), _node("node-b", _gpu("node-b", "g0", "u1"))),
            authentication_state="authenticated", evidence={"network": _network()},
        )
    )
    inventory.persist_physical_path(_concrete_path())
    scheduler = ComputeScheduler(inventory)
    with pytest.raises(ComputeSchedulingError, match="complete physical placement"):
        scheduler.placement(_requirements())


def test_verified_concrete_path_is_consumed_by_distributed_placement(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(
        ProviderResourceSnapshot(
            provider_id="provider-a", domain_id="domain-a", observed_at=time.time(),
            nodes=(_node("node-a", _gpu("node-a", "g0", "u0")), _node("node-b", _gpu("node-b", "g0", "u1"))),
            authentication_state="authenticated", evidence={"network": _network()},
        )
    )
    path = _concrete_path()
    inventory.persist_physical_path(path)
    verification = PhysicalFabricVerification.verify(
        path, evidence=[{"segment": s, "operation": "probe", "result": "pass"} for s in path.segments]
    )
    inventory.persist_physical_verification(verification, evidence={"stage": "inter_node_collective"})
    placement = ComputeScheduler(inventory).placement(_requirements())
    assert placement.selected_node_ids == ("node-a", "node-b")
    assert placement.evidence["concrete_physical_paths"][0]["path_id"] == path.path_id


def test_multiple_verified_concrete_paths_remain_available_to_placement(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path_ab = _concrete_path()
    inventory.persist_physical_path(path_ab)
    # A second independently identified path must remain selectable.
    path_ba = PhysicalFabricPathBuilder.build(
        locality_graph={"components": [
            {"component_type": "gpu", "identity": "gpu:u1", "node_id": "node-b"},
            {"component_type": "pci", "identity": "pci:dst", "node_id": "node-b"},
            {"component_type": "numa", "identity": "numa:dst", "node_id": "node-b"},
            {"component_type": "nic", "identity": "nic:dst", "node_id": "node-b"},
            {"component_type": "rdma_device", "identity": "rdma:dst", "node_id": "node-b"},
            {"component_type": "rdma_port", "identity": "rdma:dst:1", "node_id": "node-b"},
            {"component_type": "fabric", "identity": "fabric:ib0", "node_id": "domain-1"},
            {"component_type": "rdma_port", "identity": "rdma:src:1", "node_id": "node-a"},
            {"component_type": "rdma_device", "identity": "rdma:src", "node_id": "node-a"},
            {"component_type": "nic", "identity": "nic:src", "node_id": "node-a"},
            {"component_type": "numa", "identity": "numa:src", "node_id": "node-a"},
            {"component_type": "pci", "identity": "pci:src", "node_id": "node-a"},
            {"component_type": "gpu", "identity": "gpu:u0", "node_id": "node-a"},
        ], "edges": [
            {"relationship_type": "gpu_to_pci", "source": "gpu:u1", "target": "pci:dst", "state": "known"},
            {"relationship_type": "gpu_to_numa", "source": "gpu:u1", "target": "numa:dst", "state": "known"},
            {"relationship_type": "gpu_to_nic", "source": "gpu:u1", "target": "nic:dst", "state": "known"},
            {"relationship_type": "nic_to_rdma_device", "source": "nic:dst", "target": "rdma:dst", "state": "known"},
            {"relationship_type": "rdma_device_to_port", "source": "rdma:dst", "target": "rdma:dst:1", "state": "known"},
            {"relationship_type": "rdma_port_to_fabric", "source": "rdma:dst:1", "target": "fabric:ib0", "state": "known"},
            {"relationship_type": "fabric_to_rdma_port", "source": "fabric:ib0", "target": "rdma:src:1", "state": "known"},
            {"relationship_type": "rdma_device_to_port", "source": "rdma:src", "target": "rdma:src:1", "state": "known"},
            {"relationship_type": "nic_to_rdma_device", "source": "nic:src", "target": "rdma:src", "state": "known"},
            {"relationship_type": "gpu_to_nic", "source": "gpu:u0", "target": "nic:src", "state": "known"},
            {"relationship_type": "gpu_to_numa", "source": "gpu:u0", "target": "numa:src", "state": "known"},
            {"relationship_type": "gpu_to_pci", "source": "gpu:u0", "target": "pci:src", "state": "known"},
        ]}, source_gpu="gpu:u1", destination_gpu="gpu:u0")[0]
    inventory.persist_physical_path(path_ba)
    assert {item["path_id"] for item in inventory.physical_paths()} == {path_ab.path_id, path_ba.path_id}


def test_recovery_evidence_requires_fresh_verified_path(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = _concrete_path()
    inventory.persist_physical_path(path)
    verification = PhysicalFabricVerification.verify(
        path, evidence=[{"segment": s, "operation": "probe", "result": "pass"} for s in path.segments]
    )
    inventory.persist_physical_verification(verification, evidence={"stage": "path_verification"})
    failed = PhysicalFabricVerification.fail(
        verification, reason="RDMA path failure", failure_domain="rdma_port"
    )
    inventory.persist_physical_verification(failed, evidence={"stage": "failure", "path_id": path.path_id})
    assert inventory.physical_verification_history()[-1]["state"] == "FAILED"
    assert inventory.physical_verification_history()[-1]["evidence"]["path_id"] == path.path_id
