from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_reconciliation import reconcile_allocations
from lead_engine.compute_scheduler import ComputeScheduler
from lead_engine.compute_resources import (
    ComputeRequirements,
    CpuResource,
    GpuRequirements,
    GpuResource,
    NodeResource,
    ResourceState,
    WorkloadClass,
)
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_pool import WorkerIdentity


def _snapshot():
    gpu = GpuResource(
        node_id="node-a",
        gpu_id="gpu-0",
        gpu_uuid="uuid-a",
        model="NVIDIA",
        vram_bytes=16 * 1024**3,
        compute_capability="8.0",
        driver_version="550",
        cuda_version="12.4",
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    node = NodeResource(
        node_id="node-a",
        architecture="x86_64",
        cpu=CpuResource("node-a", 8, 32 * 1024**3),
        gpus=(gpu,),
        state=ResourceState.AVAILABLE,
    )
    return ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=100.0,
        nodes=(node,),
    )


def _requirements():
    return ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        gpu=GpuRequirements(gpu_count=1, min_vram_bytes=8 * 1024**3),
    )


def test_reconcile_releases_completed_bound_allocation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "leads.sqlite3"))
    inventory.observe(_snapshot())
    scheduler = ComputeScheduler(inventory)
    allocation = scheduler.allocate(_requirements(), "allocation-1")

    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="token", lease_seconds=30)
    coordinator.register_worker(WorkerIdentity("worker-1", "host", "x86_64", 8, 32768, ("agent",)))
    task_id = coordinator.enqueue({"kind": "agent_task", "agent": "agent", "payload": {}})
    claimed = coordinator.claim("worker-1")
    assert coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        allocation_id=allocation.allocation_id,
        provider_id=allocation.provider_id,
        domain_id=allocation.domain_id,
        resource_ids=allocation.resource_ids,
        lease_token=claimed["lease_token"],
    )
    assert coordinator.complete("worker-1", task_id, claimed["lease_token"], {"ok": True})

    result = reconcile_allocations(inventory, coordinator)
    assert result["released_count"] == 1
    assert inventory.get(allocation.resource_keys[0])["state"] == ResourceState.AVAILABLE.value
    assert inventory.allocation(allocation.allocation_id)["state"] == "released"


def test_reconcile_repairs_stranded_terminal_fabric_allocation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "leads.sqlite3"))
    inventory.observe(_snapshot())
    scheduler = ComputeScheduler(inventory)
    allocation = scheduler.allocate(_requirements(), "allocation-1")

    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="token",
        lease_seconds=30,
        inventory=inventory,
    )
    coordinator.register_worker(WorkerIdentity("worker-1", "host", "x86_64", 8, 32768, ("agent",)))
    task_id = coordinator.enqueue({"kind": "agent_task", "agent": "agent", "payload": {}})
    claimed = coordinator.claim("worker-1")
    assert inventory.bind_allocation(
        allocation.allocation_id,
        task_id=task_id,
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        lease_token_digest=__import__("hashlib").sha256(
            claimed["lease_token"].encode("utf-8")
        ).hexdigest(),
    )
    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_execution_attempts SET status='failed',finished_at=?,"
            "error='simulated crash after attempt retirement',authoritative_acceptance='rejected' "
            "WHERE attempt_id=?",
            (__import__("time").time(), claimed["attempt_id"]),
        )
        connection.commit()

    result = reconcile_allocations(inventory, coordinator)
    assert result["released_count"] == 1
    assert inventory.allocation(allocation.allocation_id)["state"] == "released"
    assert inventory.get(allocation.resource_keys[0])["state"] == ResourceState.AVAILABLE.value


def test_reconcile_releases_expired_attempt_and_allows_new_generation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "leads.sqlite3"))
    inventory.observe(_snapshot())
    scheduler = ComputeScheduler(inventory)
    allocation = scheduler.allocate(_requirements(), "allocation-1")

    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="token", lease_seconds=30)
    coordinator.register_worker(WorkerIdentity("worker-1", "host", "x86_64", 8, 32768, ("agent",)))
    task_id = coordinator.enqueue({"kind": "agent_task", "agent": "agent", "payload": {}})
    claimed = coordinator.claim("worker-1")
    assert coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        allocation_id=allocation.allocation_id,
        provider_id=allocation.provider_id,
        domain_id=allocation.domain_id,
        resource_ids=allocation.resource_ids,
        lease_token=claimed["lease_token"],
    )
    with coordinator._connect() as connection:
        connection.execute("UPDATE compute_tasks SET lease_until=0 WHERE task_id=?", (task_id,))
        connection.commit()

    result = reconcile_allocations(inventory, coordinator)
    assert result["expired_recovered_count"] == 1
    assert result["released_count"] == 1
    assert inventory.get(allocation.resource_keys[0])["state"] == ResourceState.AVAILABLE.value

    new_claim = coordinator.claim("worker-1")
    assert new_claim["task_id"] == task_id
    assert new_claim["generation"] == 2
    assert new_claim["attempt_id"] != claimed["attempt_id"]

def test_reconcile_old_generation_cannot_release_new_generation_allocation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "leads.sqlite3"))
    first = _snapshot()
    second_gpu = GpuResource(
        node_id="node-b",
        gpu_id="gpu-0",
        gpu_uuid="uuid-b",
        model="NVIDIA",
        vram_bytes=16 * 1024**3,
        compute_capability="8.0",
        driver_version="550",
        cuda_version="12.4",
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    second_node = NodeResource(
        node_id="node-b",
        architecture="x86_64",
        cpu=CpuResource("node-b", 8, 32 * 1024**3),
        gpus=(second_gpu,),
        state=ResourceState.AVAILABLE,
    )
    snapshot = ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=101.0,
        nodes=first.nodes + (second_node,),
    )
    inventory.observe(snapshot)
    scheduler = ComputeScheduler(inventory)
    old_allocation = scheduler.allocate(_requirements(), "old-allocation")

    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="token",
        lease_seconds=30,
        inventory=inventory,
    )
    coordinator.register_worker(WorkerIdentity("worker-1", "host-a", "x86_64", 8, 32768, ("agent",)))
    coordinator.register_worker(WorkerIdentity("worker-2", "host-b", "x86_64", 8, 32768, ("agent",)))
    task_id = coordinator.enqueue({"kind": "agent_task", "agent": "agent", "payload": {}})
    old_claim = coordinator.claim("worker-1")
    assert coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=old_claim["attempt_id"],
        generation=old_claim["generation"],
        allocation_id=old_allocation.allocation_id,
        provider_id=old_allocation.provider_id,
        domain_id=old_allocation.domain_id,
        resource_ids=old_allocation.resource_ids,
        lease_token=old_claim["lease_token"],
    )

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_execution_attempts SET status='failed',finished_at=?,"
            "error='old generation failed',authoritative_acceptance='rejected' WHERE attempt_id=?",
            (__import__("time").time(), old_claim["attempt_id"]),
        )
        connection.execute(
            "UPDATE compute_tasks SET status='queued',worker_id=NULL,attempt_id=NULL,"
            "lease_token_digest=NULL,lease_until=NULL WHERE task_id=?",
            (task_id,),
        )
        connection.commit()
    coordinator.pool.release_task_slot("worker-1")

    new_claim = coordinator.claim("worker-2")
    assert new_claim["task_id"] == task_id
    assert new_claim["generation"] == old_claim["generation"] + 1

    new_allocation = scheduler.allocate(_requirements(), "new-allocation")
    assert coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=new_claim["attempt_id"],
        generation=new_claim["generation"],
        allocation_id=new_allocation.allocation_id,
        provider_id=new_allocation.provider_id,
        domain_id=new_allocation.domain_id,
        resource_ids=new_allocation.resource_ids,
        lease_token=new_claim["lease_token"],
    )

    result = reconcile_allocations(inventory, coordinator)
    assert old_allocation.allocation_id in result["released"]
    assert inventory.allocation(old_allocation.allocation_id)["state"] == "released"
    assert inventory.allocation(new_allocation.allocation_id)["state"] == "reserved"
    assert inventory.get(new_allocation.resource_keys[0])["state"] == ResourceState.RESERVED.value
