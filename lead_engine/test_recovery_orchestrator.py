from __future__ import annotations

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
from lead_engine.recovery_orchestrator import RecoveryOrchestrator


def _path(path_id: str) -> PhysicalFabricPath:
    return PhysicalFabricPath(
        path_id=path_id,
        source_gpu=f"gpu:{path_id}:a",
        destination_gpu=f"gpu:{path_id}:b",
        segments=(f"gpu:{path_id}:a", f"rdma:{path_id}:1"),
        fabric_domains=(f"domain:{path_id}",),
        state=FabricPathState.VERIFIED,
    )


def _measurement(path_id: str, gpu_uuid: str) -> dict[str, object]:
    return {
        "fabric_path_id": path_id,
        "measurement_status": "measured",
        "verified": True,
        "remote_test_server_verified": True,
        "worker_id": f"worker:{path_id}",
        "remote_worker_id": f"remote:{path_id}",
        "remote_endpoint": f"endpoint:{path_id}",
        "gpu_uuid": gpu_uuid,
        "rdma_device": f"rdma:{path_id}",
        "rdma_port": 1,
        "bandwidth_gbps": 100.0,
    }


def _physical_evidence(path: PhysicalFabricPath) -> tuple[dict[str, str], ...]:
    return tuple({"segment": segment, "result": "pass"} for segment in path.segments)


def test_orchestrator_discovers_all_triggered_paths_without_dropping_existing_actions(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    paths = tuple(_path(f"path-{index}") for index in range(4))
    for index, path in enumerate(paths):
        inventory.persist_physical_path(path)
        inventory.fail_physical_path(path.path_id, reason=f"failure-{index}", observed_at=10.0 + index)

    orchestrator = RecoveryOrchestrator(inventory)
    first = orchestrator.discover(now=20.0)
    second = orchestrator.discover(now=21.0)

    assert {item["path_id"] for item in first} == {path.path_id for path in paths}
    assert {item["path_id"] for item in second} == {path.path_id for path in paths}
    assert len(inventory.active_path_recovery_actions()) == len(paths)


def test_orchestrator_execution_is_exact_path_scoped_and_closes_only_after_stable_evidence(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path_a = _path("path-a")
    path_b = _path("path-b")
    for path in (path_a, path_b):
        inventory.persist_physical_path(path)
        inventory.record_active_gdrdma_measurement(
            path_id=path.path_id,
            measurement=_measurement(path.path_id, f"{path.path_id}:a"),
            observed_at=1.0,
        )
        inventory.record_active_gdrdma_measurement(
            path_id=path.path_id,
            measurement=_measurement(path.path_id, f"{path.path_id}:a"),
            observed_at=2.0,
        )
    inventory.fail_physical_path(path_a.path_id, reason="path-a failure", observed_at=10.0)

    orchestrator = RecoveryOrchestrator(inventory)
    action = orchestrator.discover(now=20.0)[0]
    result = orchestrator.execute(
        action_id=action["action_id"],
        owner="recovery-worker-a",
        physical_evidence=_physical_evidence(path_a),
        active_measurement=_measurement(path_a.path_id, f"{path_a.path_id}"),
        observed_at=21.0,
        now=21.0,
    )

    assert result["state"] == "SUCCEEDED"
    assert result["allow_routing"] is True
    path_a_record = next(item for item in inventory.physical_paths() if item["path_id"] == path_a.path_id)
    assert path_a_record["state"] == FabricPathState.MEASURED.value
    path_b_record = next(item for item in inventory.physical_paths() if item["path_id"] == path_b.path_id)
    assert path_b_record["state"] == FabricPathState.MEASURED.value


def test_orchestrator_does_not_reactivate_stale_generation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = _path("stale")
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="first failure", observed_at=10.0)
    orchestrator = RecoveryOrchestrator(inventory)
    first = orchestrator.discover(now=20.0)[0]

    inventory.fail_physical_path(path.path_id, reason="second failure", observed_at=30.0)
    second = orchestrator.discover(now=31.0)[-1]
    assert second["generation"] == first["generation"] + 1

    result = orchestrator.execute(
        action_id=first["action_id"],
        owner="old-worker",
        physical_evidence=_physical_evidence(path),
        observed_at=32.0,
        now=32.0,
    )

    assert result["state"] == "CANCELLED"
    assert inventory.physical_paths()[0]["state"] == FabricPathState.FAILED.value


def test_orchestrator_retries_insufficient_active_evidence_without_enabling_routing(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = _path("retry")
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="failure", observed_at=10.0)

    orchestrator = RecoveryOrchestrator(inventory)
    action = orchestrator.discover(now=20.0)[0]
    result = orchestrator.execute(
        action_id=action["action_id"],
        owner="recovery-worker",
        physical_evidence=_physical_evidence(path),
        active_measurement=_measurement(path.path_id, f"{path.path_id}:a"),
        observed_at=21.0,
        now=21.0,
    )

    assert result["state"] == "RETRY_WAIT"
    assert result["allow_routing"] is False
    stored = inventory.active_path_recovery_actions(path_id=path.path_id)[0]
    assert stored["attempt_count"] == 1
    assert stored["last_error"]


def test_orchestrator_due_actions_exposes_all_durable_work(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    for index in range(3):
        path = _path(f"due-{index}")
        inventory.persist_physical_path(path)
        inventory.fail_physical_path(path.path_id, reason=f"failure-{index}", observed_at=10.0 + index)

    orchestrator = RecoveryOrchestrator(inventory)
    orchestrator.discover(now=20.0)

    due = orchestrator.due(now=20.0)
    assert {item["path_id"] for item in due} == {"due-0", "due-1", "due-2"}


def test_orchestrator_requires_the_existing_inventory_evidence_gates(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = _path("gates")
    inventory.persist_physical_path(path)
    inventory.fail_physical_path(path.path_id, reason="failure", observed_at=10.0)

    orchestrator = RecoveryOrchestrator(inventory)
    action = orchestrator.discover(now=20.0)[0]

    result = orchestrator.execute(
        action_id=action["action_id"],
        owner="recovery-worker",
        physical_evidence=({"segment": path.segments[0], "result": "pass"},),
        observed_at=21.0,
        now=21.0,
    )

    assert result["state"] == "RETRY_WAIT"
    assert result["allow_routing"] is False
    assert inventory.physical_paths()[0]["state"] == FabricPathState.FAILED.value
