from __future__ import annotations

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
from lead_engine.recovery_orchestrator import RecoveryOrchestrator
from lead_engine.healing_authorities import HealingAuthorityError, HealingAuthorityGateway


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
        "observed_at": observed_at,
    }


def _physical_evidence(path: PhysicalFabricPath) -> tuple[dict[str, str], ...]:
    return tuple({"segment": segment, "result": "pass"} for segment in path.segments)


def test_gateway_binds_exact_physical_active_and_recovery_authorities(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = _path("path-a")
    inventory.persist_physical_path(path)
    inventory.record_active_gdrdma_measurement(
        path_id=path.path_id, measurement=_measurement(path.path_id, 1.0, 200.0)
    )
    inventory.record_active_gdrdma_measurement(
        path_id=path.path_id, measurement=_measurement(path.path_id, 2.0, 198.0)
    )
    orchestrator = RecoveryOrchestrator(inventory)
    discovered = orchestrator.discover(now=4.0)
    assert discovered and discovered[0]["path_id"] == path.path_id

    gateway = HealingAuthorityGateway(inventory=inventory, recovery_orchestrator=orchestrator)
    evidence = gateway.path(path.path_id)

    assert evidence["path_id"] == path.path_id
    assert evidence["physical"]["path_id"] == path.path_id
    assert evidence["physical"]["source_gpu"] == path.source_gpu
    assert evidence["active_path"]["path_id"] == path.path_id
    assert evidence["active_path"]["state"] == "degrading"
    assert evidence["recovery_actions"][0]["path_id"] == path.path_id
    assert evidence["authorities"] == (
        "compute_inventory",
        "active_path_intelligence",
        "recovery_orchestrator",
    )


def test_gateway_never_synthesizes_unknown_path(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    orchestrator = RecoveryOrchestrator(inventory)
    gateway = HealingAuthorityGateway(inventory=inventory, recovery_orchestrator=orchestrator)

    with pytest.raises(HealingAuthorityError, match="unknown physical fabric path"):
        gateway.path("path-that-does-not-exist")


def test_gateway_delegates_exact_path_recovery_to_authoritative_orchestrator(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="path-recover",
        source_gpu="gpu:path-recover:a",
        destination_gpu="gpu:path-recover:b",
        segments=("gpu:path-recover:a", "rdma:path-recover:1"),
        fabric_domains=("domain:path-recover",),
        state=FabricPathState.DEGRADED,
    )
    inventory.persist_physical_path(path)
    inventory.record_active_gdrdma_measurement(
        path_id=path.path_id, measurement=_measurement(path.path_id, 1.0, 200.0)
    )
    inventory.record_active_gdrdma_measurement(
        path_id=path.path_id, measurement=_measurement(path.path_id, 2.0, 198.0)
    )
    inventory.fail_physical_path(path.path_id, reason="link failure", observed_at=3.0)
    orchestrator = RecoveryOrchestrator(inventory)
    gateway = HealingAuthorityGateway(inventory=inventory, recovery_orchestrator=orchestrator)

    result = gateway.recover_path(
        path_id=path.path_id,
        owner="healer-1",
        physical_evidence=_physical_evidence(path),
        active_measurement=_measurement(path.path_id, 4.0, 199.0),
        now=4.0,
        observed_at=4.0,
    )

    assert result["path_id"] == path.path_id
    assert result["state"] == "SUCCEEDED"
    assert result["allow_routing"] is True
    assert result["delegated_to"] == "recovery_orchestrator"
    assert result["active_path"]["path_id"] == path.path_id
    assert result["active_path"]["state"] == "stable"
    assert inventory.active_path_recovery_actions(path_id=path.path_id)[0]["state"] == "SUCCEEDED"
