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

def test_inventory_derives_active_path_intelligence_from_immutable_test_history(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="fabric-path-intel",
        source_gpu="gpu:GPU-a",
        destination_gpu="gpu:GPU-b",
        segments=("gpu:GPU-a", "pci:0000:17:00.0", "nic:ib0", "rdma:mlx5_0:1", "fabric:domain-1", "rdma:mlx5_1:1", "nic:ib1", "gpu:GPU-b"),
        fabric_domains=("fabric:domain-1",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    for observed_at, bandwidth in ((1.0, 200.0), (2.0, 198.0), (3.0, 140.0)):
        inventory.record_active_gdrdma_measurement(
            path_id=path.path_id,
            measurement={
                "measurement_status": "measured",
                "verified": True,
                "test": "ib_write_bw",
                "fabric_path_id": path.path_id,
                "worker_id": "worker-a",
                "gpu_uuid": "GPU-a",
                "rdma_device": "mlx5_0",
                "rdma_port": 1,
                "remote_worker_id": "worker-b",
                "remote_endpoint": "198.51.100.10",
                "remote_test_server_verified": True,
                "direction": "client_to_server",
                "mode": "cuda_dmabuf",
                "bandwidth_gbps": bandwidth,
            },
            evidence={"raw_output": "RDMA_Write BW Test"},
            observed_at=observed_at,
        )

    intelligence = inventory.active_path_intelligence(path_id=path.path_id)

    assert intelligence["state"] == "degrading"
    assert intelligence["comparable_sample_count"] == 3
    assert intelligence["baseline"]["bandwidth_gbps"] == 199.0
    assert intelligence["latest"]["bandwidth_gbps"] == 140.0
    assert intelligence["synthetic_baseline"] is False


def test_route_health_carries_exact_active_path_intelligence_without_synthesizing_route_health(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="fabric-path-health-intel",
        source_gpu="gpu:GPU-a",
        destination_gpu="gpu:GPU-b",
        segments=("gpu:GPU-a", "pci:0000:17:00.0", "nic:ib0", "rdma:mlx5_0:1", "fabric:domain-1", "rdma:mlx5_1:1", "nic:ib1", "gpu:GPU-b"),
        fabric_domains=("fabric:domain-1",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.record_active_gdrdma_measurement(
        path_id=path.path_id,
        measurement={
            "measurement_status": "measured", "verified": True, "test": "ib_write_bw",
            "fabric_path_id": path.path_id, "worker_id": "worker-a", "gpu_uuid": "GPU-a",
            "rdma_device": "mlx5_0", "rdma_port": 1, "remote_worker_id": "worker-b",
            "remote_endpoint": "198.51.100.10", "remote_test_server_verified": True,
            "direction": "client_to_server", "mode": "cuda_dmabuf", "bandwidth_gbps": 180.0,
        }, observed_at=1.0,
    )
    inventory.record_fabric_route_observation({}, fabric_path_id=path.path_id, latency_ms=2.0, success=True, observed_at=1.0)

    health = inventory.fabric_route_health_index()

    assert health[path.path_id]["sample_count"] == 1
    assert health[path.path_id]["active_path_intelligence"]["state"] == "insufficient_evidence"
    assert health[path.path_id]["active_path_intelligence"]["synthetic_baseline"] is False


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



def test_active_path_recovery_plan_turns_failed_exact_path_into_required_fresh_verification(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="fabric-path-recovery",
        source_gpu="gpu:GPU-a",
        destination_gpu="gpu:GPU-b",
        segments=("gpu:GPU-a", "pci:0000:17:00.0", "nic:ib0", "rdma:mlx5_0:1", "fabric:domain-1", "rdma:mlx5_1:1", "nic:ib1", "gpu:GPU-b"),
        fabric_domains=("fabric:domain-1",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active path test failed", observed_at=10.0)

    plan = inventory.active_path_recovery_plan(path_id=path.path_id)

    assert plan["path_id"] == path.path_id
    assert plan["action"] == "fresh_physical_reverification_required"
    assert plan["required_segments"] == path.segments
    assert plan["allow_routing"] is False


def test_active_path_recovery_requires_complete_fresh_evidence_before_reactivation(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="fabric-path-recovery-apply",
        source_gpu="gpu:GPU-a",
        destination_gpu="gpu:GPU-b",
        segments=("gpu:GPU-a", "pci:0000:17:00.0", "nic:ib0"),
        fabric_domains=("fabric:domain-1",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active path test failed", observed_at=10.0)

    with pytest.raises(ValueError, match="fresh path-segment evidence is incomplete"):
        inventory.apply_active_path_reverification(
            path_id=path.path_id,
            evidence=({"segment": "gpu:GPU-a", "result": "pass"},),
            observed_at=11.0,
        )

    assert inventory.physical_paths()[0]["state"] == FabricPathState.FAILED.value


def test_active_path_reverification_reactivates_only_exact_failed_path_with_complete_new_evidence(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="fabric-path-recovery-success",
        source_gpu="gpu:GPU-a",
        destination_gpu="gpu:GPU-b",
        segments=("gpu:GPU-a", "pci:0000:17:00.0", "nic:ib0"),
        fabric_domains=("fabric:domain-1",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active path test failed", observed_at=10.0)

    result = inventory.apply_active_path_reverification(
        path_id=path.path_id,
        evidence=tuple({"segment": segment, "result": "pass"} for segment in path.segments),
        observed_at=11.0,
    )

    assert result["state"] == FabricPathState.REVERIFIED.value
    assert result["allow_routing"] is False
    assert result["next_action"] == "fresh_active_measurement_required"
    assert result["path_id"] == path.path_id
    assert inventory.physical_paths()[0]["state"] == FabricPathState.REVERIFIED.value
    history = inventory.physical_verification_history()
    assert history[-1]["state"] == FabricPathState.REVERIFIED.value
    assert history[-1]["observed_at"] == 11.0



def test_closed_loop_recovery_stops_after_physical_reverification_and_requires_active_measurement(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(path_id="cycle", source_gpu="gpu:a", destination_gpu="gpu:b", segments=("gpu:a", "rdma:mlx5_0:1"), fabric_domains=("d",), state=FabricPathState.VERIFIED)
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="failure", observed_at=10.0)
    result = inventory.execute_active_path_recovery_cycle(path_id=path.path_id, physical_evidence=tuple({"segment": s, "result": "pass"} for s in path.segments), observed_at=11.0)
    assert result["stage"] == "physical_reverification"
    assert result["allow_routing"] is False
    assert inventory.physical_paths()[0]["state"] == FabricPathState.REVERIFIED.value


def test_closed_loop_recovery_requires_verified_active_measurement_before_routing(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(path_id="cycle-active", source_gpu="gpu:a", destination_gpu="gpu:b", segments=("gpu:a", "rdma:mlx5_0:1"), fabric_domains=("d",), state=FabricPathState.VERIFIED)
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="failure", observed_at=10.0)
    physical = tuple({"segment": s, "result": "pass"} for s in path.segments)
    measurement = {"fabric_path_id": path.path_id, "measurement_status": "measured", "verified": True, "remote_test_server_verified": True, "worker_id": "w", "remote_worker_id": "rw", "remote_endpoint": "ep", "gpu_uuid": "a", "rdma_device": "mlx5_0", "rdma_port": 1, "bandwidth_gbps": 100.0}
    result = inventory.execute_active_path_recovery_cycle(path_id=path.path_id, physical_evidence=physical, active_measurement=measurement, observed_at=11.0)
    assert result["stage"] == "active_measurement"
    assert result["test_id"]
    assert inventory.physical_paths()[0]["state"] == FabricPathState.MEASURED.value


def test_recovery_action_is_durable_and_deduplicated_per_exact_path_generation(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="recovery-action-path",
        source_gpu="gpu:a",
        destination_gpu="gpu:b",
        segments=("gpu:a", "rdma:mlx5_0:1"),
        fabric_domains=("d",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active failure", observed_at=10.0)

    first = inventory.ensure_active_path_recovery_action(path_id=path.path_id)
    duplicate = inventory.ensure_active_path_recovery_action(path_id=path.path_id)

    assert first["action_id"] == duplicate["action_id"]
    assert first["generation"] == 1
    assert first["state"] == "PENDING"
    assert first["required_stage"] == "fresh_physical_reverification_required"
    assert inventory.active_path_recovery_actions(path_id=path.path_id) == [first]


def test_recovery_action_claim_is_single_owner_and_expiry_allows_reclaim(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="recovery-claim-path",
        source_gpu="gpu:a",
        destination_gpu="gpu:b",
        segments=("gpu:a", "rdma:mlx5_0:1"),
        fabric_domains=("d",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active failure", observed_at=10.0)
    action = inventory.ensure_active_path_recovery_action(path_id=path.path_id)

    claimed = inventory.claim_active_path_recovery_action(action_id=action["action_id"], owner="worker-1", now=20.0, lease_seconds=30.0)
    blocked = inventory.claim_active_path_recovery_action(action_id=action["action_id"], owner="worker-2", now=21.0, lease_seconds=30.0)
    reclaimed = inventory.claim_active_path_recovery_action(action_id=action["action_id"], owner="worker-2", now=51.0, lease_seconds=30.0)

    assert claimed["owner"] == "worker-1"
    assert blocked is None
    assert reclaimed["owner"] == "worker-2"
    assert reclaimed["attempt_count"] == 2


def test_recovery_action_closes_only_after_physical_and_stable_active_gates(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="recovery-controller-path",
        source_gpu="gpu:a",
        destination_gpu="gpu:b",
        segments=("gpu:a", "rdma:mlx5_0:1"),
        fabric_domains=("d",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active failure", observed_at=10.0)
    action = inventory.ensure_active_path_recovery_action(path_id=path.path_id, now=20.0)

    physical = tuple({"segment": s, "result": "pass"} for s in path.segments)
    measurement = {
        "fabric_path_id": path.path_id,
        "measurement_status": "measured",
        "verified": True,
        "remote_test_server_verified": True,
        "worker_id": "w",
        "remote_worker_id": "rw",
        "remote_endpoint": "ep",
        "gpu_uuid": "a",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "bandwidth_gbps": 100.0,
    }
    result = inventory.execute_active_path_recovery_action(
        action_id=action["action_id"],
        owner="worker-1",
        physical_evidence=physical,
        active_measurement=measurement,
        observed_at=21.0,
    )

    assert result["state"] == "SUCCEEDED"
    assert result["allow_routing"] is True
    assert inventory.active_path_recovery_actions(path_id=path.path_id)[0]["state"] == "SUCCEEDED"
    assert inventory.physical_paths()[0]["state"] == FabricPathState.MEASURED.value


def test_recovery_action_retries_without_closing_when_active_evidence_is_not_stable(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="recovery-retry-path",
        source_gpu="gpu:a",
        destination_gpu="gpu:b",
        segments=("gpu:a", "rdma:mlx5_0:1"),
        fabric_domains=("d",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="active failure", observed_at=10.0)
    action = inventory.ensure_active_path_recovery_action(path_id=path.path_id, now=20.0)
    physical = tuple({"segment": s, "result": "pass"} for s in path.segments)
    measurement = {
        "fabric_path_id": path.path_id, "measurement_status": "measured",
        "verified": True, "remote_test_server_verified": True,
        "worker_id": "w", "remote_worker_id": "rw", "remote_endpoint": "ep",
        "gpu_uuid": "a", "rdma_device": "mlx5_0", "rdma_port": 1,
        "bandwidth_gbps": 100.0,
    }
    result = inventory.execute_active_path_recovery_action(
        action_id=action["action_id"], owner="worker-1",
        physical_evidence=physical, active_measurement=measurement, observed_at=21.0,
    )

    assert result["state"] == "RETRY_WAIT"
    assert result["allow_routing"] is False
    assert result["retry_in_seconds"] > 0
    assert inventory.active_path_recovery_actions(path_id=path.path_id)[0]["state"] == "RETRY_WAIT"


def test_stale_recovery_action_cannot_reactivate_a_newer_exact_path_generation(tmp_path):
    from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="recovery-stale-path",
        source_gpu="gpu:a",
        destination_gpu="gpu:b",
        segments=("gpu:a", "rdma:mlx5_0:1"),
        fabric_domains=("d",),
        state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="failure-one", observed_at=10.0)
    first = inventory.ensure_active_path_recovery_action(path_id=path.path_id, now=20.0)

    inventory.fail_physical_path(path.path_id, reason="failure-two", observed_at=30.0)
    second = inventory.ensure_active_path_recovery_action(path_id=path.path_id, now=31.0)
    assert second["generation"] == first["generation"] + 1

    result = inventory.execute_active_path_recovery_action(
        action_id=first["action_id"], owner="worker-1",
        physical_evidence=tuple({"segment": s, "result": "pass"} for s in path.segments),
        observed_at=32.0,
    )

    assert result["state"] == "CANCELLED"
    assert inventory.physical_paths()[0]["state"] == FabricPathState.FAILED.value
