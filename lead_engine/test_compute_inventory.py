import time

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


def _snapshot(*, gpus=(), ephemeral=False, expires_at=None, authentication_state="authenticated"):
    return ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(NodeResource(
            node_id="node-1",
            architecture="x86_64",
            cpu=CpuResource("node-1", 16, 64 * 1024**3),
            gpus=tuple(gpus),
        ),),
        ephemeral=ephemeral,
        expires_at=expires_at,
        authentication_state=authentication_state,
        evidence={"probe": "test"},
    )


def _gpu(gpu_id, uuid):
    return GpuResource(
        node_id="node-1",
        gpu_id=gpu_id,
        gpu_uuid=uuid,
        model="NVIDIA Test GPU",
        vram_bytes=24 * 1024**3,
    )



def test_active_gdrdma_measurement_is_durable_and_tied_to_exact_fabric_path(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="fabric-path-1",
        source_gpu="gpu:GPU-a",
        destination_gpu="gpu:GPU-b",
        segments=("gpu:GPU-a", "pci:0000:17:00.0", "nic:ib0", "rdma:mlx5_0:1", "fabric:domain-1", "rdma:mlx5_1:1", "nic:ib1", "gpu:GPU-b"),
        fabric_domains=("fabric:domain-1",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)

    measurement = {
        "measurement_status": "measured",
        "verified": True,
        "test": "ib_write_bw",
        "fabric_path_id": "fabric-path-1",
        "worker_id": "worker-a",
        "gpu_uuid": "GPU-a",
        "rdma_port": 1,
        "remote_worker_id": "worker-b",
        "remote_endpoint": "198.51.100.10",
        "remote_test_server_verified": True,
        "mode": "cuda_dmabuf",
        "bandwidth_gbps": 187.5,
        "latency_us": 4.25,
    }
    measurement_id = inventory.record_active_gdrdma_measurement(
        path_id="fabric-path-1",
        measurement=measurement,
        evidence={"raw_output": "RDMA_Write BW Test", "direction": "client_to_server"},
        observed_at=1000.0,
    )

    path_row = next(item for item in inventory.physical_paths() if item["path_id"] == "fabric-path-1")
    history = inventory.physical_fabric_measurement_history(path_id="fabric-path-1")
    assert measurement_id
    assert path_row["state"] == FabricPathState.MEASURED.value
    assert path_row["measurement"]["fabric_path_id"] == "fabric-path-1"
    assert path_row["measurement"]["bandwidth_gbps"] == 187.5
    assert path_row["measurement_observed_at"] == 1000.0
    assert len(history) == 1
    assert history[0]["measurement"]["remote_worker_id"] == "worker-b"


def test_active_gdrdma_measurement_rejects_unknown_path_without_persistence(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    with pytest.raises(ValueError, match="fabric path does not exist"):
        inventory.record_active_gdrdma_measurement(
            path_id="missing-path",
            measurement={
                "verified": True,
                "fabric_path_id": "missing-path",
                "remote_worker_id": "worker-b",
                "remote_endpoint": "198.51.100.10",
            },
            evidence={},
            observed_at=1000.0,
        )

def test_multiple_gpus_are_independently_addressable(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    result = inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"), _gpu("1", "uuid-1"))))
    assert result["observed_gpus"] == 2
    resources = [item for item in inventory.resources() if item["resource_type"] == "gpu"]
    assert {item["resource_key"] for item in resources} == {
        "provider-a/domain-a/node-1/gpu/uuid-0",
        "provider-a/domain-a/node-1/gpu/uuid-1",
    }


def test_missing_gpu_uuid_is_not_fabricated(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", ""),)))
    gpu = next(item for item in inventory.resources() if item["resource_type"] == "gpu")
    assert gpu["identity_key"] == "node-1/0"
    assert '"gpu_uuid": ""' in gpu["payload_json"]


def test_provider_disappearance_preserves_history(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),)))
    changed = inventory.mark_provider_missing("provider-a", "domain-a")
    assert changed == 2
    assert len(inventory.resources()) == 2
    assert all(item["state"] == ResourceState.DEGRADED.value for item in inventory.resources())


def test_ephemeral_expiration_removes_eligibility_but_keeps_identity(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),), ephemeral=True, expires_at=time.time() - 1))
    assert inventory.eligible() == []
    assert inventory.get("provider-a/domain-a/node-1/gpu/uuid-0") is not None


def test_quarantined_resource_is_not_eligible(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),)))
    key = "provider-a/domain-a/node-1/gpu/uuid-0"
    assert inventory.mark_state(key, ResourceState.QUARANTINED)
    assert inventory.eligible() == []


def test_resource_state_evidence_is_retained(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),)))
    gpu = inventory.get("provider-a/domain-a/node-1/gpu/uuid-0")
    assert gpu is not None
    assert '"probe": "test"' in gpu["evidence_json"]


def test_one_gpu_failure_does_not_quarantine_unrelated_gpu(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"), _gpu("1", "uuid-1"))))
    failed_key = "provider-a/domain-a/node-1/gpu/uuid-0"
    healthy_key = "provider-a/domain-a/node-1/gpu/uuid-1"
    assert inventory.mark_state(failed_key, ResourceState.QUARANTINED)
    assert inventory.get(failed_key)["state"] == ResourceState.QUARANTINED.value
    assert inventory.get(healthy_key)["state"] != ResourceState.QUARANTINED.value


def test_provider_authentication_state_is_retained(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(authentication_state="reauth_required"))
    resource = inventory.get("provider-a/domain-a/node-1/cpu")
    assert resource is not None
    assert resource["authentication_state"] == "reauth_required"


def test_existing_inventory_schema_is_migrated(tmp_path):
    db_path = tmp_path / "inventory.sqlite3"
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute("""CREATE TABLE compute_resource_inventory (
            resource_key TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            domain_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            gpu_id TEXT,
            identity_key TEXT,
            resource_type TEXT NOT NULL,
            state TEXT NOT NULL,
            observed_at REAL NOT NULL,
            expires_at REAL,
            ephemeral INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL)""")
        connection.commit()

    inventory = ComputeInventory(str(db_path))
    columns = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(compute_resource_inventory)")}
    assert "authentication_state" in columns


def test_provider_observation_preserves_reserved_resource_state(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    snapshot = _snapshot(gpus=(_gpu("0", "uuid-0"),))
    inventory.observe(snapshot)
    key = "provider-a/domain-a/node-1/gpu/uuid-0"
    inventory.mark_state(key, ResourceState.RESERVED)
    inventory.observe(snapshot)
    assert inventory.get(key)["state"] == ResourceState.RESERVED.value


def test_inventory_quarantines_one_failed_physical_path_with_durable_reason(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    snapshot = _snapshot_with_gpu("GPU-0")
    inventory.observe(snapshot)
    key = "provider/domain/node-1/gpu/GPU-0"
    assert inventory.quarantine_resource(
        key,
        reason="NCCL selected an HCA port different from the scheduler's verified physical path",
        evidence={"failure_class": "planned_actual_physical_path_mismatch", "rdma_device": "mlx5_0", "rdma_port": 2},
    )
    resource = inventory.get(key)
    assert resource["state"] == ResourceState.QUARANTINED.value
    evidence = json.loads(resource["evidence_json"])
    assert evidence["quarantine"]["reason"].startswith("NCCL selected an HCA")
    assert evidence["quarantine"]["failure_class"] == "planned_actual_physical_path_mismatch"
    assert key not in {row["resource_key"] for row in inventory.eligible()}


def test_fabric_path_quarantine_is_durable_and_revalidation_is_explicit(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = {
        "node_id": "node-a",
        "gpu_uuid": "u0",
        "nic": "eth1",
        "rdma_device": "mlx5_1",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    key = inventory.quarantine_fabric_path(
        path,
        reason="RDMA link went down",
        evidence={"failure_class": "rdma_link_down"},
    )
    assert key == inventory.fabric_path_key(path)
    assert inventory.is_fabric_path_quarantined(path) is True
    rows = inventory.quarantined_fabric_paths()
    assert len(rows) == 1
    assert rows[0]["gpu_uuid"] == "u0"
    assert rows[0]["rdma_device"] == "mlx5_1"
    assert rows[0]["rdma_port"] == 1
    with pytest.raises(ValueError):
        inventory.revalidate_fabric_path(path, verification={"verified": False})
    assert inventory.is_fabric_path_quarantined(path) is True
    assert inventory.revalidate_fabric_path(path, verification={"verified": True, **path}) is True
    assert inventory.is_fabric_path_quarantined(path) is False
    assert inventory.quarantined_fabric_paths() == []
