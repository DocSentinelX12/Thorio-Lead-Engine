import pytest
import json
import threading
import time
from pathlib import Path

from lead_engine.compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_pool import WorkerIdentity
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
from lead_engine.compute_worker import ComputeWorkerClient


def _fabric_worker(node_id: str) -> WorkerIdentity:
    return WorkerIdentity(
        node_id,
        f"{node_id}.host",
        "x86_64",
        8,
        16384,
        ("lead-processing",),
        (GpuResource(node_id=node_id, gpu_id="gpu-0", gpu_uuid=f"GPU-{node_id}-0", availability_state=ResourceState.AVAILABLE),),
        "550.1",
        "12.4",
        "2.20",
    )


def _register_inventory(coordinator: ComputeCoordinator, inventory: ComputeInventory) -> None:
    for node_id in ("worker-1", "worker-2"):
        coordinator.pool.register(_fabric_worker(node_id))
        inventory.observe(ProviderResourceSnapshot(
            provider_id="fabric-provider",
            domain_id="fabric-domain",
            observed_at=time.time(),
            expires_at=time.time() + 300,
            ephemeral=True,
            authentication_state="authenticated",
            evidence={"source": "test"},
            nodes=(NodeResource(
                node_id=node_id,
                architecture="x86_64",
                cpu=CpuResource(node_id, 8, 16384),
                gpus=(GpuResource(
                    node_id=node_id, gpu_id="gpu-0", gpu_uuid=f"GPU-{node_id}-0",
                    availability_state=ResourceState.AVAILABLE,
                ),),
                driver_version="550.1",
                cuda_version="12.4",
                nccl_version="2.20",
                state=ResourceState.AVAILABLE,
            ),),
        ))



def _valid_execution_verification(coordinator: ComputeCoordinator, attempt_id: str, worker_id: str) -> dict:
    attempt = coordinator.execution_attempt(attempt_id)
    endpoint = str(attempt["rendezvous_endpoint"] or "10.0.0.5:29400")
    launch = coordinator.fabric_launch_plan_for_worker(
        attempt_id=attempt_id,
        generation=int(attempt["generation"]),
        worker_id=worker_id,
        lease_token=str(coordinator.task(attempt["task_id"])["lease_token"]),
        rendezvous_endpoint=endpoint,
    )
    participant = next(item for item in launch["workers"] if item["worker_id"] == worker_id)
    expected_sum = launch["world_size"] * (launch["world_size"] + 1) // 2
    return {
        "verified": True,
        "backend": "nccl",
        "collective": "all_reduce",
        "world_size": launch["world_size"],
        "nnodes": launch["nnodes"],
        "network_transport": "IB",
        "worker_id": worker_id,
        "gpu_identity": {"verified": True, "gpu_bindings": participant["gpu_bindings"]},
        "gpu_bindings": participant["gpu_bindings"],
        "process_evidence": [
            {
                "rank": binding["rank"],
                "local_rank": binding["local_rank"],
                "gpu_binding": binding,
                "probe": {
                    "backend": "nccl",
                    "collective": "all_reduce",
                    "verified_on_gpu": True,
                    "world_size": launch["world_size"],
                    "nnodes": launch["nnodes"],
                    "expected_sum": expected_sum,
                    "rank": binding["rank"],
                    "gpu_uuid": binding["gpu_uuid"],
                    "network_transport": "IB",
                },
                "rdma_devices": ["mlx5_0"],
                "verified_rdma_devices": ["mlx5_0"],
                "hca_selections": [{"device": "mlx5_0", "port": 1, "transport": "IB"}],
                "verified_hca_selections": [{"device": "mlx5_0", "port": 1, "transport": "IB"}],
                "verified_rdma_links": [{
                    "rdma_device": "mlx5_0",
                    "port": 1,
                    "netdev": "eth0",
                    "pci_bus_id": "0000:41:00.0",
                    "state": "ACTIVE",
                    "physical_state": "LINK_UP",
                    "link_layer": "InfiniBand",
                    "gids": ["fe80::1122:3344:5566:7788"],
                }],
                "gpu_nic_locality": {
                    "gpu_uuid": binding["gpu_uuid"],
                    "nic": "eth0",
                    "nic_pci_bus_id": "0000:41:00.0",
                    "shared_pci_ancestor": "0000:40",
                    "source": "sysfs",
                    "rdma_device": "mlx5_0",
                    "rdma_port": 1,
                    "rdma_pci_bus_id": "0000:41:00.0",
                    "link_layer": "InfiniBand",
                },
            }
            for binding in participant["gpu_bindings"]
        ],
    }

def test_recorded_verification_persists_verified_rdma_path_evidence(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    lease_token = claimed["lease_token"]
    verification = _valid_execution_verification(coordinator, attempt_id, "worker-1")
    for item in verification["process_evidence"]:
        item.pop("rdma_devices", None)
        item.pop("verified_rdma_devices", None)
    assert coordinator.record_execution_verification(
        attempt_id=attempt_id,
        generation=claimed["generation"],
        worker_id="worker-1",
        lease_token=lease_token,
        verification=verification,
    ) is False
    for item in verification["process_evidence"]:
        item["rdma_devices"] = ["mlx5_0"]
        item["verified_rdma_devices"] = ["mlx5_0"]
    assert coordinator.record_execution_verification(
        attempt_id=attempt_id,
        generation=claimed["generation"],
        worker_id="worker-1",
        lease_token=lease_token,
        verification=verification,
    ) is True
    participant = coordinator.execution_participants(attempt_id)[0]
    import json
    stored_verification = json.loads(participant["verification"])
    assert stored_verification["process_evidence"][0]["verified_rdma_devices"] == ["mlx5_0"]


def test_worker_receives_durable_participant_and_launch_contract(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id

    server = ComputeCoordinatorServer(coordinator, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ComputeWorkerClient(
            f"http://127.0.0.1:{server.server_port}",
            "test-token",
            "worker-1",
            timeout_seconds=2,
        )
        assignments = client.fabric_assignments()
        assert len(assignments) == 1
        assignment = assignments[0]
        assert assignment["attempt_id"] == claimed["attempt_id"]
        assert assignment["generation"] == claimed["generation"]
        assert assignment["worker_id"] == "worker-1"
        assert assignment["lease_token"] == claimed["lease_token"]
        assert coordinator.execution_attempt(claimed["attempt_id"])["placement_id"]
        assert inventory.placement(coordinator.execution_attempt(claimed["attempt_id"])["placement_id"]) is not None

        plan = client.fabric_launch_plan(
            assignment["attempt_id"],
            assignment["generation"],
            assignment["lease_token"],
            "10.0.0.5:29400",
        )
        assert plan["world_size"] == 2
        assert plan["nnodes"] == 2
        assert plan["rendezvous_endpoint"] == "10.0.0.5:29400"
        assert plan["rendezvous_id"] == assignment["rendezvous_ref"]
        assert plan["workers"][0]["node_rank"] == 0
        assert plan["workers"][1]["node_rank"] == 1
        assert plan["workers"][0]["process_count"] == 1
        assert plan["workers"][1]["process_count"] == 1

        heartbeat = client.fabric_heartbeat(
            assignment["attempt_id"],
            assignment["generation"],
            assignment["lease_token"],
        )
        assert heartbeat["ok"] is True
        participant = coordinator.execution_participants(claimed["attempt_id"])[0]
        assert participant["status"] == "active"
        assert participant["heartbeat_at"] >= participant["bound_at"]
        assert coordinator.task(task_id)["status"] == "leased"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_fabric_launch_requires_explicit_rendezvous_endpoint(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id
    try:
        coordinator.fabric_launch_plan_for_worker(
            attempt_id=claimed["attempt_id"],
            generation=claimed["generation"],
            worker_id="worker-1",
            lease_token=claimed["lease_token"],
            rendezvous_endpoint="",
        )
    except ValueError as error:
        assert "host:port" in str(error)
    else:
        raise AssertionError("fabric launch accepted a missing rendezvous endpoint")


def test_fabric_recovery_does_not_release_unrelated_worker_task_slot(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id

    with coordinator.pool._connect() as connection:
        connection.execute(
            "UPDATE compute_workers SET current_load=1,last_heartbeat=? WHERE worker_id=?",
            (time.time(), "worker-1"),
        )
        connection.execute(
            "UPDATE compute_workers SET last_heartbeat=? WHERE worker_id=?",
            (time.time() - 3600, "worker-2"),
        )
        connection.commit()

    result = coordinator.reconcile_fabric(participant_timeout_seconds=30)
    assert result == {"reconciled": 1, "requeued": 1}
    assert coordinator.pool.worker("worker-1")["current_load"] == 1


def test_fabric_reconciliation_requeues_when_worker_liveness_is_lost(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id
    plan = coordinator.fabric_launch_plan_for_worker(
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        worker_id="worker-1",
        lease_token=claimed["lease_token"],
        rendezvous_endpoint="10.0.0.1:29500",
    )
    assert plan["attempt_id"] == claimed["attempt_id"]

    with coordinator.pool._connect() as connection:
        connection.execute(
            "UPDATE compute_workers SET last_heartbeat=? WHERE worker_id=?",
            (time.time() - 3600, "worker-2"),
        )
        connection.commit()

    result = coordinator.reconcile_fabric(participant_timeout_seconds=30)
    assert result == {"reconciled": 1, "requeued": 1}
    assert coordinator.task(task_id)["status"] == "queued"


def test_fabric_recovery_releases_allocation_for_fresh_generation(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    first = coordinator.claim_physical()
    assert first["task_id"] == task_id
    allocation_id = first["physical_allocation"]["allocation_id"]

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_workers SET last_heartbeat=? WHERE worker_id=?",
            (time.time() - 3600, "worker-2"),
        )
        connection.commit()

    assert coordinator.reconcile_fabric(participant_timeout_seconds=30) == {
        "reconciled": 1,
        "requeued": 1,
    }
    assert inventory.allocation(allocation_id)["state"] == "released"
    assert all(
        inventory.get(resource_key)["state"] == ResourceState.AVAILABLE.value
        for resource_key in first["physical_allocation"]["resource_keys"]
    )

    second = coordinator.claim_physical()
    assert second["task_id"] == task_id
    assert second["generation"] == first["generation"] + 1
    assert second["attempt_id"] != first["attempt_id"]
    assert second["physical_allocation"]["allocation_id"] != allocation_id


def test_fabric_reconciliation_requeues_entire_attempt_when_one_participant_is_lost(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id
    attempt_id = claimed["attempt_id"]

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_execution_participants SET heartbeat_at=? WHERE attempt_id=? AND worker_id=?",
            (time.time() - 1000, attempt_id, "worker-2"),
        )
        connection.commit()

    result = coordinator.reconcile_fabric(participant_timeout_seconds=30)
    assert result == {"reconciled": 1, "requeued": 1}

    task = coordinator.task(task_id)
    assert task["status"] == "queued"
    assert task["lease_token"] is None
    assert task["attempt_id"] == attempt_id

    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["status"] == "failed"
    assert attempt["authoritative_acceptance"] == "rejected"
    participants = coordinator.execution_participants(attempt_id)
    assert {item["status"] for item in participants} == {"failed"}
    assert all(item["last_error"] == "fabric participant lost" for item in participants)

    allocation = inventory.allocation(claimed["physical_allocation"]["allocation_id"])
    assert allocation["state"] == "released"



def test_execution_verification_rejects_gpu_identity_not_in_launch_contract(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    verification = _valid_execution_verification(coordinator, attempt_id, "worker-1")
    verification["process_evidence"][0]["probe"]["gpu_uuid"] = "GPU-not-allocated"
    assert coordinator.record_execution_verification(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
        verification=verification,
    ) is False


def test_fabric_launch_plan_rejects_inactive_execution_attempt(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    lease_token = claimed["lease_token"]

    coordinator.fabric_launch_plan_for_worker(
        attempt_id=attempt_id,
        generation=claimed["generation"],
        worker_id="worker-1",
        lease_token=lease_token,
        rendezvous_endpoint="10.0.0.5:29400",
    )

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_execution_attempts SET status='completed',authoritative_acceptance='accepted' WHERE attempt_id=?",
            (attempt_id,),
        )
        connection.commit()

    try:
        coordinator.fabric_launch_plan(attempt_id, "10.0.0.5:29400")
    except ValueError as error:
        assert str(error) == "execution attempt lease is not active"
    else:
        raise AssertionError("launch planning accepted a completed execution attempt")


def test_fabric_convergence_requires_every_participant_and_is_idempotent(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    coordinator.record_execution_verification(
        attempt_id=attempt_id, generation=generation,
        worker_id="worker-1", lease_token=lease_token,
        verification=_valid_execution_verification(coordinator, attempt_id, "worker-1"),
    )
    waiting = coordinator.converge_fabric_execution(
        attempt_id=attempt_id, generation=generation,
        worker_id="worker-1", lease_token=lease_token,
    )
    assert waiting["converged"] is False
    assert waiting["reason"] == "awaiting_all_participant_verifications"
    assert waiting["verified_participants"] == 1

    coordinator.record_execution_verification(
        attempt_id=attempt_id, generation=generation,
        worker_id="worker-2", lease_token=lease_token,
        verification=_valid_execution_verification(coordinator, attempt_id, "worker-2"),
    )
    converged = coordinator.converge_fabric_execution(
        attempt_id=attempt_id, generation=generation,
        worker_id="worker-2", lease_token=lease_token,
    )
    assert converged == {"converged": True, "status": "completed", "already_completed": False}

    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["status"] == "completed"
    assert attempt["authoritative_acceptance"] == "accepted"
    evidence = json.loads(attempt["verification"])
    assert [item["worker_id"] for item in evidence["participants"]] == ["worker-1", "worker-2"]

    task = coordinator.task(task_id)
    assert task["status"] == "leased"
    allocation = inventory.allocation(claimed["physical_allocation"]["allocation_id"])
    assert allocation["state"] == "bound"

    repeated = coordinator.converge_fabric_execution(
        attempt_id=attempt_id, generation=generation,
        worker_id="worker-1", lease_token=lease_token,
    )
    assert repeated == {"converged": True, "status": "completed", "already_completed": True}


def test_fabric_rendezvous_endpoint_is_bound_once_and_cannot_change(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    first = coordinator.fabric_launch_plan_for_worker(
        attempt_id=attempt_id, generation=generation,
        worker_id="worker-1", lease_token=lease_token,
        rendezvous_endpoint="10.0.0.5:29400",
    )
    assert first["rendezvous_endpoint"] == "10.0.0.5:29400"

    try:
        coordinator.fabric_launch_plan_for_worker(
            attempt_id=attempt_id, generation=generation,
            worker_id="worker-2", lease_token=lease_token,
            rendezvous_endpoint="10.0.0.6:29400",
        )
    except ValueError as error:
        assert "durable execution endpoint" in str(error)
    else:
        raise AssertionError("durable rendezvous endpoint was changed")


def test_converged_attempt_is_not_downgraded_by_authoritative_completion(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    for worker_id in ("worker-1", "worker-2"):
        coordinator.record_execution_verification(
            attempt_id=attempt_id,
            generation=generation,
            worker_id=worker_id,
            lease_token=lease_token,
            verification=_valid_execution_verification(coordinator, attempt_id, worker_id),
        )
    coordinator.converge_fabric_execution(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
    )

    assert coordinator.complete(
        f"fabric:{attempt_id}",
        task_id,
        lease_token,
        {"business_result": "authoritatively accepted"},
    ) is True

    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["status"] == "completed"
    assert attempt["authoritative_acceptance"] == "accepted"
    assert coordinator.task(task_id)["status"] == "completed"
    allocation = inventory.allocation(claimed["physical_allocation"]["allocation_id"])
    assert allocation["state"] == "released"

    assert coordinator.complete(
        f"fabric:{attempt_id}",
        task_id,
        lease_token,
        {"business_result": "authoritatively accepted"},
    ) is True
    assert inventory.allocation(claimed["physical_allocation"]["allocation_id"])["state"] == "released"


def test_expiration_preserves_completed_execution_and_releases_its_allocation(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    for worker_id in ("worker-1", "worker-2"):
        coordinator.record_execution_verification(
            attempt_id=attempt_id,
            generation=generation,
            worker_id=worker_id,
            lease_token=lease_token,
            verification=_valid_execution_verification(coordinator, attempt_id, worker_id),
        )
    coordinator.converge_fabric_execution(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
    )

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_tasks SET lease_until=? WHERE task_id=?",
            (time.time() - 1, task_id),
        )
        connection.commit()

    assert coordinator.recover_expired_tasks() == 1

    task = coordinator.task(task_id)
    assert task["status"] == "queued"
    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["status"] == "completed"
    assert attempt["authoritative_acceptance"] == "accepted"
    participants = coordinator.execution_participants(attempt_id)
    assert {item["status"] for item in participants} == {"completed"}
    allocation = inventory.allocation(claimed["physical_allocation"]["allocation_id"])
    assert allocation["state"] == "released"


def test_stale_participant_cannot_report_after_convergence_or_retry(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    for worker_id in ("worker-1", "worker-2"):
        coordinator.record_execution_verification(
            attempt_id=attempt_id,
            generation=generation,
            worker_id=worker_id,
            lease_token=lease_token,
            verification=_valid_execution_verification(coordinator, attempt_id, worker_id),
        )
    coordinator.converge_fabric_execution(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
    )
    assert coordinator.execution_participant_state(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-2",
        lease_token=lease_token,
        status="failed",
        error="late failure",
    ) is False

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_tasks SET lease_until=? WHERE task_id=?",
            (time.time() - 1, task_id),
        )
        connection.commit()
    coordinator.recover_expired_tasks()

    retry = coordinator.claim_physical()
    assert retry["task_id"] == task_id
    assert retry["generation"] == generation + 1
    assert coordinator.execution_participant_state(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
        status="failed",
        error="stale generation report",
    ) is False


def test_expired_generation_cannot_complete_after_retry(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    old_attempt_id = claimed["attempt_id"]
    old_lease_token = claimed["lease_token"]

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_tasks SET lease_until=? WHERE task_id=?",
            (time.time() - 1, task_id),
        )
        connection.commit()

    assert coordinator.recover_expired_tasks() == 1
    retry = coordinator.claim_physical()
    assert retry["task_id"] == task_id
    assert retry["generation"] == claimed["generation"] + 1

    assert coordinator.complete(
        f"fabric:{old_attempt_id}",
        task_id,
        old_lease_token,
        {"stale": True},
    ) is False

    old_attempt = coordinator.execution_attempt(old_attempt_id)
    assert old_attempt["status"] == "expired"
    current_task = coordinator.task(task_id)
    assert current_task["status"] == "leased"
    assert current_task["attempt_id"] == retry["attempt_id"]


def test_convergence_rejects_an_expired_task_lease(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    for worker_id in ("worker-1", "worker-2"):
        coordinator.record_execution_verification(
            attempt_id=attempt_id,
            generation=generation,
            worker_id=worker_id,
            lease_token=lease_token,
            verification=_valid_execution_verification(coordinator, attempt_id, worker_id),
        )

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_tasks SET lease_until=? WHERE task_id=?",
            (time.time() - 1, task_id),
        )
        connection.commit()

    result = coordinator.converge_fabric_execution(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
    )
    assert result == {"converged": False, "reason": "execution_identity_rejected"}


def test_run_worker_services_fabric_assignments_before_claiming_business_work(monkeypatch):
    from lead_engine.compute_worker import run_worker

    class StopAfterFabric:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls > 0

        def wait(self, seconds):
            self.calls += 1
            return True

    class Client:
        def __init__(self):
            self._registered = False
            self.worker_id = "worker-1"
            self.fabric_seen = False
            self.claimed = False

        def register(self):
            self._registered = True
            return {"ok": True}

        def heartbeat(self, current_load=0):
            return {"ok": True}

        def fabric_assignments(self):
            self.fabric_seen = True
            return [{"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"}]

        def claim(self):
            self.claimed = True
            return None

    client = Client()
    serviced = []
    stop_event = StopAfterFabric()

    def fake_verify(client_arg, assignment, **kwargs):
        serviced.append((client_arg, assignment, kwargs["rendezvous_endpoint"]))
        stop_event.calls = 1
        return {"verified": True}

    monkeypatch.setattr("lead_engine.compute_worker.run_fabric_verification", fake_verify)

    run_worker(
        client,
        idle_seconds=1,
        heartbeat_seconds=15,
        fabric_rendezvous_endpoint="10.0.0.5:29400",
        stop_event=stop_event,
    )

    assert client.fabric_seen is True
    assert client.claimed is False
    assert serviced == [(client, {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"}, "10.0.0.5:29400")]


def test_run_worker_survives_fabric_runtime_failure(monkeypatch):
    from lead_engine.compute_worker import run_worker
    from lead_engine.nvidia_runtime import NvidiaRuntimeError

    class Stop:
        def __init__(self):
            self.done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            self.done = True
            return True

    class Client:
        def __init__(self):
            self._registered = True
            self.worker_id = "worker-1"
            self.claimed = False
        def heartbeat(self, current_load=0):
            return {"ok": True}
        def fabric_assignments(self):
            return [{"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"}]
        def claim(self):
            self.claimed = True
            return None

    client = Client()
    stop = Stop()

    def failing_verify(*args, **kwargs):
        stop.done = True
        raise NvidiaRuntimeError("real NCCL runtime unavailable")

    monkeypatch.setattr("lead_engine.compute_worker.run_fabric_verification", failing_verify)

    run_worker(
        client,
        idle_seconds=1,
        heartbeat_seconds=15,
        fabric_rendezvous_endpoint="10.0.0.5:29400",
        stop_event=stop,
    )

    assert client.claimed is False


def test_running_fabric_participant_heartbeat_renews_lease(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    assert coordinator.record_execution_verification(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
        verification=_valid_execution_verification(coordinator, attempt_id, "worker-1"),
    ) is True

    before = coordinator.task(task_id)["lease_until"]
    time.sleep(0.01)

    assert coordinator.heartbeat_execution_participant(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
    ) is True

    participant = next(
        item for item in coordinator.execution_participants(attempt_id)
        if item["worker_id"] == "worker-1"
    )
    after = coordinator.task(task_id)["lease_until"]
    assert participant["status"] == "running"
    assert after > before


def test_stale_fabric_participant_cannot_be_revived(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_execution_participants SET heartbeat_at=? WHERE attempt_id=? AND worker_id=?",
            (time.time() - 3600, attempt_id, "worker-1"),
        )
        connection.commit()

    assert coordinator.heartbeat_execution_participant(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
    ) is False

    participant = next(
        item for item in coordinator.execution_participants(attempt_id)
        if item["worker_id"] == "worker-1"
    )
    assert participant["heartbeat_at"] < time.time() - coordinator.lease_seconds

    coordinator._bind_rendezvous_endpoint(
        attempt_id,
        generation,
        lease_token,
        "10.0.0.1:29500",
    )

    try:
        coordinator.fabric_launch_plan(
            attempt_id,
            "10.0.0.1:29500",
        )
    except ValueError as error:
        assert "participant heartbeat is stale" in str(error)
    else:
        raise AssertionError("stale participant was allowed to launch")


def test_fabric_verification_preserves_runtime_failure_when_failure_reporting_fails():
    from lead_engine.compute_worker import ComputeWorkerError, run_fabric_verification
    from lead_engine.nvidia_runtime import NvidiaRuntimeError

    class Client:
        worker_id = "worker-1"

        def __init__(self):
            self.states = []

        def fabric_launch_plan(self, *args):
            return {
                "workers": [{
                    "worker_id": "worker-1",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-1-0", "rank": 0, "local_rank": 0}],
                }, {
                    "worker_id": "worker-2",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-2/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-2-0", "rank": 1, "local_rank": 0}],
                }],
                "world_size": 2,
                "nnodes": 2,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }

        def fabric_state(self, *args):
            status = args[3]
            self.states.append(status)
            if status == "failed":
                raise ComputeWorkerError("coordinator failure while recording failure")
            return {"ok": True}

        def fabric_heartbeat(self, *args):
            return {"ok": True}

    class Runtime:
        timeout_seconds = 5

        def verify_local(self):
            return {"cuda": True, "nccl": True}

        def distributed_process_command(self):
            return ["python", "-m", "lead_engine.nccl_all_reduce_probe"]

    client = Client()
    try:
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=0.01,
            runtime=Runtime(),
            runner=lambda command, timeout, env: (1, "", "NCCL exploded"),
        )
    except NvidiaRuntimeError as error:
        assert "distributed NCCL launch failed" in str(error)
    else:
        raise AssertionError("runtime failure was masked by failure-state reporting")

    assert client.states == ["launching", "active", "failed"]


def test_fabric_verification_cleans_up_when_local_runtime_validation_fails():
    from lead_engine.compute_worker import run_fabric_verification
    from lead_engine.nvidia_runtime import NvidiaRuntimeError

    class Client:
        worker_id = "worker-1"
        def __init__(self):
            self.states = []
        def fabric_launch_plan(self, *args):
            return {
                "workers": [{
                    "worker_id": "worker-1",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-1-0", "rank": 0, "local_rank": 0}],
                }, {
                    "worker_id": "worker-2",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-2/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-2-0", "rank": 1, "local_rank": 0}],
                }],
                "world_size": 2,
                "nnodes": 2,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }
        def fabric_state(self, *args):
            self.states.append(args[3])
            return {"ok": True}
        def fabric_heartbeat(self, *args):
            return {"ok": True}

    class Runtime:
        def verify_local(self):
            raise NvidiaRuntimeError("CUDA runtime validation failed")

    client = Client()
    try:
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            runtime=Runtime(),
        )
    except NvidiaRuntimeError as error:
        assert str(error) == "CUDA runtime validation failed"
    else:
        raise AssertionError("local runtime failure was not preserved")

    assert client.states == ["launching", "failed"]


def test_fabric_heartbeat_failure_terminates_live_process_and_reports_failure(monkeypatch):
    import subprocess
    from lead_engine.compute_worker import ComputeWorkerError, run_fabric_verification

    class Client:
        worker_id = "worker-1"
        def __init__(self):
            self.states = []
            self.heartbeats = 0
        def fabric_launch_plan(self, *args):
            return {
                "workers": [{
                    "worker_id": "worker-1",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-1-0", "rank": 0, "local_rank": 0}],
                }, {
                    "worker_id": "worker-2",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-2/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-2-0", "rank": 1, "local_rank": 0}],
                }],
                "world_size": 2,
                "nnodes": 2,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }
        def fabric_state(self, *args):
            self.states.append(args[3])
            return {"ok": True}
        def fabric_heartbeat(self, *args):
            self.heartbeats += 1
            return {"ok": False}

    class Runtime:
        timeout_seconds = 5
        def verify_local(self):
            return {"cuda": True, "nccl": True}
        def distributed_process_command(self):
            return ["torchrun"]
        def validate_distributed_probe_output(self, stdout, world_size, **kwargs):
            raise AssertionError("verification must not run after heartbeat loss")

    class Process:
        def __init__(self):
            self.terminated = False
            self.killed = False
            self.released = threading.Event()
        def poll(self):
            return 0 if self.terminated or self.killed else None
        def terminate(self):
            self.terminated = True
            self.released.set()
        def kill(self):
            self.killed = True
            self.released.set()
        def wait(self, timeout=None):
            if self.terminated or self.killed:
                return 143
            raise subprocess.TimeoutExpired(["torchrun"], timeout)
        def communicate(self, timeout=None):
            self.released.wait(timeout=2)
            if not (self.terminated or self.killed):
                raise AssertionError("heartbeat failure did not terminate the process")
            return "", ""
        @property
        def returncode(self):
            return 143 if self.terminated or self.killed else None

    client = Client()
    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    try:
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=0.001,
            runtime=Runtime(),
        )
    except ComputeWorkerError as error:
        assert "heartbeat failed" in str(error)
    else:
        raise AssertionError("heartbeat loss did not abort the running execution")

    assert process.terminated is True
    assert client.heartbeats >= 1
    assert client.states == ["launching", "active", "failed"]


def test_fabric_heartbeat_failure_wins_race_with_successful_process_exit():
    import time
    from lead_engine.compute_worker import ComputeWorkerError, run_fabric_verification

    class Client:
        worker_id = "worker-1"
        def __init__(self):
            self.states = []
            self.verified = False
        def fabric_launch_plan(self, *args):
            return {
                "workers": [{
                    "worker_id": "worker-1",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-1-0", "rank": 0, "local_rank": 0}],
                }, {
                    "worker_id": "worker-2",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-2/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-2-0", "rank": 1, "local_rank": 0}],
                }],
                "world_size": 2,
                "nnodes": 2,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }
        def fabric_state(self, *args):
            self.states.append(args[3])
            return {"ok": True}
        def fabric_heartbeat(self, *args):
            return {"ok": False}
        def fabric_record_verification(self, *args):
            self.verified = True
            return {"ok": True}

    class Runtime:
        timeout_seconds = 5
        def verify_local(self):
            return {"cuda": True, "nccl": True}
        def distributed_process_command(self):
            return ["torchrun"]
        def validate_distributed_probe_output(self, stdout, world_size, **kwargs):
            return {"backend": "nccl", "verified_on_gpu": True, "world_size": world_size, "collective": "all_reduce", "expected_sum": 3, "rank": kwargs["expected_rank"], "gpu_uuid": kwargs["expected_gpu_uuid"]}

    client = Client()

    def runner(command, timeout, env):
        time.sleep(0.02)
        return 0, 'THORIO_NCCL_PROBE_OK {"backend":"nccl","collective":"all_reduce","verified_on_gpu":true,"world_size":2,"expected_sum":3,"rank":0,"gpu_uuid":"GPU-worker-1-0"}', ""

    try:
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=0.001,
            runtime=Runtime(),
            runner=runner,
        )
    except ComputeWorkerError as error:
        assert "heartbeat failed" in str(error)
    else:
        raise AssertionError("successful process exit incorrectly outranked heartbeat loss")

    assert client.verified is False
    assert client.states == ["launching", "active", "failed"]


def test_fabric_process_timeout_terminates_process_and_reports_failure(monkeypatch):
    import subprocess
    from lead_engine.compute_worker import ComputeWorkerError, run_fabric_verification

    class Client:
        worker_id = "worker-1"
        def __init__(self):
            self.states = []
        def fabric_launch_plan(self, *args):
            return {
                "workers": [{
                    "worker_id": "worker-1",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-1-0", "rank": 0, "local_rank": 0}],
                }, {
                    "worker_id": "worker-2",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-2/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-2-0", "rank": 1, "local_rank": 0}],
                }],
                "world_size": 2,
                "nnodes": 2,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }
        def fabric_state(self, *args):
            self.states.append(args[3])
            return {"ok": True}
        def fabric_heartbeat(self, *args):
            return {"ok": True}

    class Runtime:
        timeout_seconds = 1
        def verify_local(self):
            return {"cuda": True, "nccl": True}
        def distributed_process_command(self):
            return ["torchrun"]

    class Process:
        def __init__(self):
            self.terminated = False
            self.killed = False
        def poll(self):
            return None if not (self.terminated or self.killed) else 143
        def terminate(self):
            self.terminated = True
        def kill(self):
            self.killed = True
        def wait(self, timeout=None):
            if self.terminated or self.killed:
                return 143
            raise subprocess.TimeoutExpired(["torchrun"], timeout)
        def communicate(self, timeout=None):
            if self.terminated or self.killed:
                return "", "terminated"
            raise subprocess.TimeoutExpired(["torchrun"], timeout)
        @property
        def returncode(self):
            return 143 if self.terminated or self.killed else None

    client = Client()
    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    try:
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=1,
            runtime=Runtime(),
        )
    except ComputeWorkerError as error:
        assert "timed out" in str(error)
    else:
        raise AssertionError("process timeout was not surfaced")

    assert process.terminated is True
    assert client.states == ["launching", "active", "failed"]


def test_fabric_unexpected_process_error_still_terminates_process(monkeypatch):
    import subprocess
    from lead_engine.compute_worker import run_fabric_verification

    class Client:
        worker_id = "worker-1"
        def __init__(self):
            self.states = []
        def fabric_launch_plan(self, *args):
            return {
                "workers": [{
                    "worker_id": "worker-1",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-1-0", "rank": 0, "local_rank": 0}],
                }, {
                    "worker_id": "worker-2",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_bindings": [{"resource_id": "worker-2/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-worker-2-0", "rank": 1, "local_rank": 0}],
                }],
                "world_size": 2,
                "nnodes": 2,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }
        def fabric_state(self, *args):
            self.states.append(args[3])
            return {"ok": True}
        def fabric_heartbeat(self, *args):
            return {"ok": True}

    class Runtime:
        timeout_seconds = 5
        def verify_local(self):
            return {"cuda": True, "nccl": True}
        def distributed_process_command(self):
            return ["torchrun"]

    class Process:
        def __init__(self):
            self.terminated = False
        def poll(self):
            return None if not self.terminated else 143
        def terminate(self):
            self.terminated = True
        def kill(self):
            self.terminated = True
        def wait(self, timeout=None):
            if self.terminated:
                return 143
            raise subprocess.TimeoutExpired(["torchrun"], timeout)
        def communicate(self, timeout=None):
            raise OSError("stdout pipe failed")
        @property
        def returncode(self):
            return 143 if self.terminated else None

    client = Client()
    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    try:
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=1,
            runtime=Runtime(),
        )
    except OSError as error:
        assert "stdout pipe failed" in str(error)
    else:
        raise AssertionError("unexpected process error was not preserved")

    assert process.terminated is True
    assert client.states == ["launching", "active", "failed"]


def test_fabric_participant_state_transitions_are_monotonic(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id
    kwargs = {
        "attempt_id": claimed["attempt_id"],
        "generation": claimed["generation"],
        "worker_id": "worker-1",
        "lease_token": claimed["lease_token"],
    }

    assert coordinator.execution_participant_state(**kwargs, status="launching") is True
    assert coordinator.execution_participant_state(**kwargs, status="active") is True
    assert coordinator.execution_participant_state(**kwargs, status="launching") is False
    assert coordinator.execution_participant_state(**kwargs, status="bound") is False


def test_fabric_heartbeat_does_not_refresh_worker_for_unauthorized_participant(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id

    with coordinator.pool._connect() as connection:
        connection.execute(
            "UPDATE compute_workers SET status='stale',last_heartbeat=? WHERE worker_id=?",
            (time.time() - 3600, "worker-1"),
        )
        connection.commit()

    assert coordinator.pool.worker("worker-1")["status"] == "stale"
    assert coordinator.heartbeat_execution_participant(
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        worker_id="worker-1",
        lease_token="not-the-active-lease",
    ) is False
    worker = coordinator.pool.worker("worker-1")
    assert worker["status"] == "stale"
    assert float(worker["last_heartbeat"]) < time.time() - 300


def test_fabric_heartbeat_refreshes_registered_worker_liveness(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id

    with coordinator.pool._connect() as connection:
        connection.execute(
            "UPDATE compute_workers SET status='stale',last_heartbeat=? WHERE worker_id=?",
            (time.time() - 3600, "worker-1"),
        )
        connection.commit()

    assert coordinator.pool.worker("worker-1")["status"] == "stale"
    assert coordinator.heartbeat_execution_participant(
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        worker_id="worker-1",
        lease_token=claimed["lease_token"],
    ) is True
    assert coordinator.pool.worker("worker-1")["status"] == "ready"



def test_verification_cannot_revive_retired_execution_generation(tmp_path: Path, monkeypatch):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    lease_token = claimed["lease_token"]
    verification = _valid_execution_verification(coordinator, attempt_id, "worker-1")

    original_launch_plan = coordinator.fabric_launch_plan

    def retire_after_launch(attempt_id_arg, endpoint):
        launch = original_launch_plan(attempt_id_arg, endpoint)
        with coordinator._connect() as connection:
            connection.execute(
                "UPDATE compute_execution_attempts SET status='failed',finished_at=?,"
                "error='simulated retirement during verification',authoritative_acceptance='rejected' "
                "WHERE attempt_id=? AND generation=? AND status='leased'",
                (time.time(), attempt_id, generation),
            )
            connection.execute(
                "UPDATE compute_tasks SET status='queued',worker_id=NULL,attempt_id=NULL,"
                "lease_token=NULL,lease_until=NULL WHERE task_id=? "
                "AND attempt_id=? AND status='leased'",
                (task_id, attempt_id),
            )
            connection.commit()
        return launch

    monkeypatch.setattr(coordinator, "fabric_launch_plan", retire_after_launch)

    assert coordinator.record_execution_verification(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
        verification=verification,
    ) is False

    participant = coordinator.execution_participants(attempt_id)[0]
    assert participant["status"] == "bound"
    assert participant["verification"] is None
    assert coordinator.execution_attempt(attempt_id)["status"] == "failed"
    assert coordinator.task(task_id)["status"] == "queued"


def test_fabric_launch_plan_constructs_verified_routes_between_participants(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=60,
        inventory=inventory,
    )
    for node_id, gpu_uuid, rdma_device, nic in (
        ("worker-1", "GPU-worker-1-0", "mlx5_0", "eth0"),
        ("worker-2", "GPU-worker-2-0", "mlx5_1", "eth1"),
    ):
        coordinator.pool.register(_fabric_worker(node_id))
        inventory.observe(ProviderResourceSnapshot(
            provider_id="fabric-provider",
            domain_id="fabric-domain",
            observed_at=time.time(),
            expires_at=time.time() + 300,
            ephemeral=True,
            authentication_state="authenticated",
            evidence={
                "source": "verified-fabric-test",
                "network": {
                    "network_domains": {"worker-1": "fabric-a", "worker-2": "fabric-a"},
                    "gpu_nic_locality": [{
                        "gpu_uuid": gpu_uuid,
                        "nic": nic,
                        "rdma_device": rdma_device,
                        "rdma_port": 1,
                        "link_layer": "InfiniBand",
                    }],
                    "rdma": {
                        "devices": [{"device": rdma_device}],
                        "links": [{
                            "rdma_device": rdma_device,
                            "port": 1,
                            "link_layer": "InfiniBand",
                            "state": "ACTIVE",
                            "physical_state": "LINK_UP",
                            "bandwidth_gbps": 200,
                            "latency_us": 4,
                        }],
                    },
                },
            },
            nodes=(NodeResource(
                node_id=node_id,
                architecture="x86_64",
                cpu=CpuResource(node_id, 8, 16384),
                gpus=(GpuResource(
                    node_id=node_id, gpu_id="gpu-0", gpu_uuid=gpu_uuid,
                    availability_state=ResourceState.AVAILABLE,
                ),),
                driver_version="550.1",
                cuda_version="12.4",
                nccl_version="2.20",
                state=ResourceState.AVAILABLE,
            ),),
        ))

    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id
    endpoint = "10.0.0.5:29400"
    assert coordinator._bind_rendezvous_endpoint(
        claimed["attempt_id"], claimed["generation"], claimed["lease_token"], endpoint
    ) == endpoint

    launch = coordinator.fabric_launch_plan(claimed["attempt_id"], endpoint)
    assert launch["world_size"] == 2
    assert launch["nnodes"] == 2
    assert len(launch["fabric_routes"]) == 1
    route = launch["fabric_routes"][0]
    assert {route["source_node_id"], route["target_node_id"]} == {"worker-1", "worker-2"}
    assert route["route_type"] == "verified_gpu_nic_rdma_fabric"
    assert all(route[key] for key in ("source_paths", "target_paths"))
    assert route["source_paths"][0]["rdma_device"] in {"mlx5_0", "mlx5_1"}
    assert route["target_paths"][0]["rdma_device"] in {"mlx5_0", "mlx5_1"}
