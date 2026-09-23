from __future__ import annotations

import time

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


def _snapshot(*, evidence: dict, observed_at: float) -> ProviderResourceSnapshot:
    gpu = GpuResource(
        node_id="node-a", gpu_id="gpu-0", gpu_uuid="GPU-UUID-0",
        vram_bytes=24 * 1024**3, compute_capability="8.0",
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    node = NodeResource(
        node_id="node-a", architecture="x86_64",
        cpu=CpuResource(node_id="node-a", cpu_count=32, memory_bytes=128 * 1024**3),
        gpus=(gpu,), state=ResourceState.HEALTHY,
    )
    return ProviderResourceSnapshot(
        provider_id="provider-a", domain_id="domain-a", observed_at=observed_at,
        nodes=(node,), authentication_state="authenticated", evidence=evidence,
    )


def test_physical_component_observation_persists_explicit_hardware_identities(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    evidence = {"physical_fabric": {"components": [{"component_type": "pci", "identity": "pci:0000:3b:00.0", "node_id": "node-a", "attributes": {"class": "display"}}, {"component_type": "numa", "identity": "numa:0", "node_id": "node-a", "attributes": {"node": 0}}, {"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a", "attributes": {"pci_bus_id": "0000:5e:00.0"}}, {"component_type": "rdma_device", "identity": "rdma:mlx5_0", "node_id": "node-a", "attributes": {"device": "mlx5_0"}}, {"component_type": "rdma_port", "identity": "rdma:mlx5_0:1", "node_id": "node-a", "parent_identity": "rdma:mlx5_0", "attributes": {"port": 1, "link_layer": "InfiniBand"}}], "relationships": [{"relationship_type": "gpu_to_nic", "source": "GPU-UUID-0", "target": "nic:mlx5_0"}]}}
    result = inventory.observe(_snapshot(evidence=evidence, observed_at=time.time()))
    assert result["observed_physical_components"] == 5
    records = inventory.physical_component_observations()
    assert {record["component_type"] for record in records} == {"pci", "numa", "nic", "rdma_device", "rdma_port"}
    nic = next(record for record in records if record["component_type"] == "nic")
    assert nic["identity"] == "nic:mlx5_0"
    assert nic["attributes"]["pci_bus_id"] == "0000:5e:00.0"


def test_repeated_observation_is_idempotent_and_preserves_multiple_paths(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    evidence = {"physical_fabric": {"components": [{"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a"}, {"component_type": "rdma_device", "identity": "rdma:mlx5_0", "node_id": "node-a"}]}}
    snapshot = _snapshot(evidence=evidence, observed_at=100.0)
    inventory.observe(snapshot); inventory.observe(snapshot)
    second_evidence = {"physical_fabric": {"components": [{"component_type": "nic", "identity": "nic:mlx5_1", "node_id": "node-a"}, {"component_type": "rdma_device", "identity": "rdma:mlx5_1", "node_id": "node-a"}]}}
    inventory.observe(_snapshot(evidence=second_evidence, observed_at=101.0))
    records = inventory.physical_component_observations()
    assert len(records) == 4
    assert {record["identity"] for record in records} == {"nic:mlx5_0", "rdma:mlx5_0", "nic:mlx5_1", "rdma:mlx5_1"}
    history = inventory.physical_component_history()
    assert len(history) == 4
    assert {item["identity"] for item in history} == {"nic:mlx5_0", "rdma:mlx5_0", "nic:mlx5_1", "rdma:mlx5_1"}


def test_newer_observation_updates_current_state_and_retains_prior_evidence(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    first = {"physical_fabric": {"components": [{"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a", "attributes": {"pci_bus_id": "0000:5e:00.0", "link_speed": "100G"}}]}}
    second = {"physical_fabric": {"components": [{"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a", "attributes": {"pci_bus_id": "0000:5e:00.0", "link_speed": "200G"}}]}}
    inventory.observe(_snapshot(evidence=first, observed_at=100.0)); inventory.observe(_snapshot(evidence=second, observed_at=101.0))
    current = inventory.physical_component_observations()
    assert len(current) == 1 and current[0]["attributes"]["link_speed"] == "200G"
    history = inventory.physical_component_history()
    assert len(history) == 2 and [item["attributes"]["link_speed"] for item in history] == ["100G", "200G"]


def test_missing_optional_hardware_fields_remain_unknown(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    evidence = {"physical_fabric": {"components": [{"component_type": "nic", "identity": "nic:unknown-pci", "node_id": "node-a", "attributes": {}}]}}
    inventory.observe(_snapshot(evidence=evidence, observed_at=100.0))
    record = inventory.physical_component_observations()[0]
    assert record["attributes"] == {} and record["pci_parent_identity"] is None and record["numa_identity"] is None


def test_physical_path_measurement_timestamp_is_durable_and_survives_reload(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    class Path:
        path_id = "path-a"; source_gpu = "gpu:src"; destination_gpu = "gpu:dst"; segments = ("gpu:src", "fabric:ib0", "gpu:dst"); fabric_domains = ("ib",); state = type("State", (), {"value": "MEASURED"})(); measurement = {"bandwidth_gbps": 180.0}
    class Verification:
        path_id = "path-a"; state = type("State", (), {"value": "MEASURED"})(); reason = None; failure_domain = None; measurement = {"bandwidth_gbps": 180.0}; measurement_observed_at = 200.0
    inventory.persist_physical_path(Path()); inventory.persist_physical_verification(Verification(), evidence={"measurement": {"bandwidth_gbps": 180.0}}, observed_at=200.0)
    rows = inventory.physical_paths(); assert rows[0]["measurement"] == {"bandwidth_gbps": 180.0} and rows[0]["measurement_observed_at"] == 200.0
    reloaded = ComputeInventory(str(tmp_path / "inventory.sqlite3")); rows = reloaded.physical_paths()
    assert rows[0]["measurement"] == {"bandwidth_gbps": 180.0} and rows[0]["measurement_observed_at"] == 200.0


def test_physical_fabric_measurement_history_retains_each_observed_capability(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, FabricVerificationResult, PhysicalFabricPath
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(path_id="path-history-1", source_gpu="gpu:src", destination_gpu="gpu:dst", segments=("gpu:src", "fabric:ib0", "gpu:dst"), fabric_domains=("fabric:ib0",), state=FabricPathState.CONSTRUCTED)
    inventory.persist_physical_path(path)
    for observed_at, bandwidth, latency, count in ((100.0, 500, 2.0, 16), (200.0, 220, 4.0, 8)):
        inventory.persist_physical_verification(FabricVerificationResult(path_id=path.path_id, state=FabricPathState.MEASURED, measurement={"bandwidth_gbps": bandwidth, "latency_us": latency, "sample_count": count}, measurement_observed_at=observed_at, required_segments=path.segments), observed_at=observed_at)
    history = inventory.physical_fabric_measurement_history()
    assert [item["observed_at"] for item in history] == [100.0, 200.0]
    assert [item["measurement"]["bandwidth_gbps"] for item in history] == [500, 220]
    assert all(item["path_id"] == path.path_id for item in history)


def test_route_health_exposes_observed_performance_change_without_threshold_policy(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    from lead_engine.physical_fabric import FabricPathState, FabricVerificationResult, PhysicalFabricPath
    path = PhysicalFabricPath(path_id="route-health-1", source_gpu="gpu:src", destination_gpu="gpu:dst", segments=("gpu:src", "fabric:ib0", "gpu:dst"), fabric_domains=("fabric:ib0",), state=FabricPathState.CONSTRUCTED)
    inventory.persist_physical_path(path)
    for observed_at, bandwidth, latency in ((100.0, 500.0, 2.0), (200.0, 400.0, 3.0), (300.0, 350.0, 5.0)):
        inventory.persist_physical_verification(FabricVerificationResult(path_id=path.path_id, state=FabricPathState.MEASURED, measurement={"bandwidth_gbps": bandwidth, "latency_us": latency, "sample_count": 8}, measurement_observed_at=observed_at, required_segments=path.segments), observed_at=observed_at)
    health = inventory.physical_fabric_route_health(path_id=path.path_id)
    assert health["path_id"] == path.path_id and health["observation_count"] == 3
    assert health["latest"]["observed_at"] == 300.0 and health["latest"]["measurement"]["latency_us"] == 5.0
    assert health["change"]["bandwidth_gbps"] == -150.0 and health["change"]["latency_us"] == 3.0
    assert health["latest"]["state"] == "MEASURED"


def test_route_health_survives_inventory_reload_and_isolated_paths(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, FabricVerificationResult, PhysicalFabricPath
    db = str(tmp_path / "inventory.sqlite3"); inventory = ComputeInventory(db)
    for path_id, values in (("path-a", ((100.0, 500.0, 2.0), (200.0, 450.0, 2.5))), ("path-b", ((100.0, 300.0, 6.0), (200.0, 320.0, 5.5)))):
        path = PhysicalFabricPath(path_id=path_id, source_gpu="gpu:src", destination_gpu="gpu:dst", segments=("gpu:src", f"fabric:{path_id}", "gpu:dst"), fabric_domains=(path_id,), state=FabricPathState.CONSTRUCTED)
        inventory.persist_physical_path(path)
        for observed_at, bandwidth, latency in values:
            inventory.persist_physical_verification(FabricVerificationResult(path_id=path_id, state=FabricPathState.MEASURED, measurement={"bandwidth_gbps": bandwidth, "latency_us": latency, "sample_count": 8}, measurement_observed_at=observed_at, required_segments=path.segments), observed_at=observed_at)
    reloaded = ComputeInventory(db)
    a = reloaded.physical_fabric_route_health(path_id="path-a"); b = reloaded.physical_fabric_route_health(path_id="path-b")
    assert a["change"]["bandwidth_gbps"] == -50.0 and b["change"]["bandwidth_gbps"] == 20.0
    assert a["latest"]["latency_us"] == 2.5 and b["latest"]["latency_us"] == 5.5


def test_route_health_with_no_history_is_evidence_empty_not_healthy(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    assert inventory.physical_fabric_route_health(path_id="missing") == {"path_id": "missing", "observation_count": 0, "latest": None, "change": {}}
