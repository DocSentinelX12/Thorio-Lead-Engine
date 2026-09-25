from __future__ import annotations

from lead_engine.fabric_topology import PhysicalFabricTopology
from lead_engine.physical_fabric import PhysicalFabricPathBuilder


def _component(identity: str, component_type: str, node_id: str) -> dict[str, object]:
    return {"identity": identity, "component_type": component_type, "node_id": node_id}


def _rel(kind: str, source: str, target: str) -> dict[str, object]:
    return {
        "relationship_type": kind,
        "source": source,
        "target": target,
        "state": "known",
        "evidence": {"source": "test-physical-probe"},
    }


def test_gpu_nic_topology_parser_reads_gpu_to_nic_columns_and_nic_legend() -> None:
    text = """
GPU0 GPU1 NIC0 NIC1 CPU Affinity NUMA Affinity GPU NUMA ID
GPU0 X NV18 PIX SYS 0-31 0 N/A
GPU1 NV18 X SYS PIX 0-31 0 N/A
NIC0 PIX SYS X PIX
NIC1 SYS PIX PIX X

Legend:
X = Self
SYS = Connection traversing PCIe as well as the SMP interconnect between NUMA nodes
NODE = Connection traversing PCIe as well as the interconnect between PCIe Host Bridges within a NUMA node
PHB = Connection traversing PCIe as well as a PCIe Host Bridge
PXB = Connection traversing multiple PCIe switches
PIX = Connection traversing at most a single PCIe switch
NV# = Connection traversing a bonded set of # NVLinks

NIC Legend:
NIC0: mlx5_0
NIC1: mlx5_1
"""

    parsed = PhysicalFabricTopology.parse_gpu_nic_matrix(text)

    assert parsed["gpu_ids"] == ["0", "1"]
    assert parsed["nic_ids"] == ["mlx5_0", "mlx5_1"]
    assert parsed["matrix"]["0"]["mlx5_0"] == "PIX"
    assert parsed["matrix"]["0"]["mlx5_1"] == "SYS"
    assert parsed["matrix"]["1"]["mlx5_0"] == "SYS"
    assert parsed["matrix"]["1"]["mlx5_1"] == "PIX"


def test_gpu_nic_topology_parser_supports_direct_netdev_columns() -> None:
    text = """
GPU0 mlx5_0 CPU Affinity NUMA Affinity
GPU0 X NODE 0-31 0
mlx5_0 NODE X
"""

    parsed = PhysicalFabricTopology.parse_gpu_nic_matrix(text)

    assert parsed["nic_ids"] == ["mlx5_0"]
    assert parsed["matrix"]["0"]["mlx5_0"] == "NODE"


def test_path_builder_preserves_independent_pcie_and_numa_alternatives() -> None:
    components = [
        _component("gpu:src", "gpu", "node-a"),
        _component("gpu:dst", "gpu", "node-b"),
        _component("pci:src-a", "pci", "node-a"),
        _component("pci:src-b", "pci", "node-a"),
        _component("numa:src-a", "numa", "node-a"),
        _component("numa:src-b", "numa", "node-a"),
        _component("nic:src", "nic", "node-a"),
        _component("rdma:src", "rdma_device", "node-a"),
        _component("rdma:src:1", "rdma_port", "node-a"),
        _component("fabric:ib0", "fabric", "domain-a"),
        _component("rdma:dst:1", "rdma_port", "node-b"),
        _component("rdma:dst", "rdma_device", "node-b"),
        _component("nic:dst", "nic", "node-b"),
        _component("numa:dst", "numa", "node-b"),
        _component("pci:dst", "pci", "node-b"),
    ]
    relationships = [
        _rel("gpu_to_pci", "gpu:src", "pci:src-a"),
        _rel("gpu_to_pci", "gpu:src", "pci:src-b"),
        _rel("gpu_to_numa", "gpu:src", "numa:src-a"),
        _rel("gpu_to_numa", "gpu:src", "numa:src-b"),
        _rel("gpu_to_nic", "gpu:src", "nic:src"),
        _rel("nic_to_rdma_device", "nic:src", "rdma:src"),
        _rel("rdma_device_to_port", "rdma:src", "rdma:src:1"),
        _rel("rdma_port_to_fabric", "rdma:src:1", "fabric:ib0"),
        _rel("fabric_to_rdma_port", "fabric:ib0", "rdma:dst:1"),
        _rel("rdma_device_to_port", "rdma:dst", "rdma:dst:1"),
        _rel("nic_to_rdma_device", "nic:dst", "rdma:dst"),
        _rel("gpu_to_nic", "gpu:dst", "nic:dst"),
        _rel("gpu_to_numa", "gpu:dst", "numa:dst"),
        _rel("gpu_to_pci", "gpu:dst", "pci:dst"),
    ]

    paths = PhysicalFabricPathBuilder.build(
        locality_graph={"components": components, "edges": relationships},
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )

    assert len(paths) == 4
    assert {path.segments[1] for path in paths} == {"pci:src-a", "pci:src-b"}
    assert {path.segments[2] for path in paths} == {"numa:src-a", "numa:src-b"}


def test_path_builder_rejects_relationships_with_wrong_component_types() -> None:
    components = [
        _component("gpu:src", "gpu", "node-a"),
        _component("gpu:dst", "gpu", "node-b"),
        _component("nic:src", "pci", "node-a"),
        _component("nic:dst", "nic", "node-b"),
    ]
    relationships = [
        _rel("gpu_to_nic", "gpu:src", "nic:src"),
        _rel("gpu_to_nic", "gpu:dst", "nic:dst"),
    ]

    assert PhysicalFabricPathBuilder.build(
        locality_graph={"components": components, "edges": relationships},
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    ) == ()


def test_inventory_stale_physical_observation_does_not_replace_newer_current_state(tmp_path) -> None:
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState

    def snapshot(observed_at: float, speed: str) -> ProviderResourceSnapshot:
        gpu = GpuResource(
            node_id="node-a", gpu_id="0", gpu_uuid="GPU-0", vram_bytes=1,
            compute_capability="8.0", health_state=ResourceState.HEALTHY,
            availability_state=ResourceState.AVAILABLE,
        )
        node = NodeResource(
            node_id="node-a", architecture="x86_64",
            cpu=CpuResource("node-a", 1, 1), gpus=(gpu,), state=ResourceState.HEALTHY,
        )
        return ProviderResourceSnapshot(
            provider_id="provider-a", domain_id="domain-a", observed_at=observed_at,
            nodes=(node,), authentication_state="authenticated",
            evidence={"physical_fabric": {"components": [{
                "component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a",
                "attributes": {"speed": speed},
            }]}},
        )

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(snapshot(200.0, "200G"))
    inventory.observe(snapshot(100.0, "100G"))

    current = inventory.physical_component_observations()
    history = inventory.physical_component_history()
    assert current[0]["attributes"]["speed"] == "200G"
    assert [item["attributes"]["speed"] for item in history] == ["200G", "100G"]


def test_inventory_stale_verification_does_not_regress_current_path_state(tmp_path) -> None:
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.physical_fabric import FabricPathState, FabricVerificationResult, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="path-1", source_gpu="gpu:src", destination_gpu="gpu:dst",
        segments=("gpu:src", "fabric:ib0", "gpu:dst"), fabric_domains=("fabric:ib0",),
    )
    inventory.persist_physical_path(path)
    verified = FabricVerificationResult(path_id="path-1", state=FabricPathState.MEASURED, measurement={"bandwidth_gbps": 200}, measurement_observed_at=200.0, required_segments=path.segments)
    inventory.persist_physical_verification(verified, observed_at=200.0)
    stale = FabricVerificationResult(path_id="path-1", state=FabricPathState.CONSTRUCTED, reason="stale", required_segments=path.segments)
    inventory.persist_physical_verification(stale, observed_at=100.0)

    current = inventory.physical_paths()[0]
    assert current["state"] == "MEASURED"
    assert current["measurement"]["bandwidth_gbps"] == 200


def test_failed_path_persistence_retains_failure_reason_and_domain(tmp_path) -> None:
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.physical_fabric import PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.persist_physical_path(PhysicalFabricPath(
        path_id="path-failure", source_gpu="gpu:src", destination_gpu="gpu:dst",
        segments=("gpu:src", "fabric:ib0", "gpu:dst"), fabric_domains=("fabric:ib0",),
    ))

    assert inventory.fail_physical_path(
        "path-failure", reason="RDMA port failed", evidence={"failure_domain": "rdma_port"}, observed_at=100.0
    )
    current = inventory.physical_paths()[0]
    assert current["state"] == "FAILED"
    assert current["reason"] == "RDMA port failed"
    assert current["failure_domain"] == "rdma_port"
