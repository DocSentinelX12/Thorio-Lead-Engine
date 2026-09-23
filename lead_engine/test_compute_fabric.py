import tempfile
import time
from pathlib import Path

import pytest

from lead_engine.compute_fabric import ComputeFabricController, ComputeFabricOrchestrator, ComputeProviderRegistry, FabricCycleReport
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ComputeProvider, ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, ComputeRequirements, GpuRequirements, GpuResource, NodeResource, ResourceState, WorkloadClass


class Provider(ComputeProvider):
    provider_id = "provider-a"

    def __init__(self, snapshot, state="healthy"):
        self.snapshot = snapshot
        self.state = state
        self.closed = False

    def discover(self):
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot

    def health(self):
        return {"provider_id": self.provider_id, "state": self.state}

    def close(self):
        self.closed = True


def snapshot(*, provider_id="provider-a", domain_id="domain-a", expires_at=None):
    gpu = GpuResource(
        node_id="node-1", gpu_id="0", gpu_uuid="GPU-1", model="NVIDIA H100",
        vram_bytes=80 * 1024**3, compute_capability="9.0",
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    return ProviderResourceSnapshot(
        provider_id=provider_id, domain_id=domain_id, observed_at=time.time(),
        nodes=(NodeResource("node-1", "x86_64", CpuResource("node-1", 16, 128 * 1024**3), (gpu,), state=ResourceState.AVAILABLE),),
        expires_at=expires_at, evidence={"source": "provider-test"},
    )


def test_registry_requires_unique_provider_domain_identity():
    registry = ComputeProviderRegistry()
    first = Provider(snapshot())
    registry.register(first, domain_id="domain-a")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Provider(snapshot()), domain_id="domain-a")
    assert registry.provider("provider-a", "domain-a") is first
    assert registry.providers() == (first,)


def test_refresh_publishes_provider_observation_into_durable_inventory():
    with tempfile.TemporaryDirectory() as directory:
        inventory = ComputeInventory(str(Path(directory) / "inventory.sqlite3"))
        registry = ComputeProviderRegistry()
        provider = Provider(snapshot())
        registry.register(provider, domain_id="domain-a")
        fabric = ComputeFabricOrchestrator(inventory, registry=registry)
        report = fabric.refresh()
        assert report.observed[0].provider_id == "provider-a"
        assert report.observed[0].observed_gpus == 1
        assert report.eligible_resources == 2
        health = fabric.health()
        assert health["registered_providers"] == 1
        assert health["eligible_resources"] == 2
        assert health["eligible_resources_by_provider"] == {"provider-a": 2}


def test_refresh_never_fabricates_capacity_after_provider_failure():
    with tempfile.TemporaryDirectory() as directory:
        inventory = ComputeInventory(str(Path(directory) / "inventory.sqlite3"))
        registry = ComputeProviderRegistry()
        provider = Provider(RuntimeError("provider unavailable"))
        registry.register(provider, domain_id="domain-a")
        fabric = ComputeFabricOrchestrator(inventory, registry=registry)
        report = fabric.refresh()
        assert report.observed[0].state == "action_required"
        assert report.observed[0].observed_gpus == 0
        assert report.eligible_resources == 0
        assert "RuntimeError" in (report.observed[0].error or "")


def test_refresh_with_explicit_provider_disappearance_withdraws_inventory():
    with tempfile.TemporaryDirectory() as directory:
        inventory = ComputeInventory(str(Path(directory) / "inventory.sqlite3"))
        registry = ComputeProviderRegistry()
        provider = Provider(snapshot())
        registry.register(provider, domain_id="domain-a")
        fabric = ComputeFabricOrchestrator(inventory, registry=registry)
        fabric.refresh()
        provider.snapshot = RuntimeError("gone")
        provider.state = "unavailable"
        report = fabric.refresh()
        assert report.observed[0].state == "unavailable"
        assert report.eligible_resources == 0
        assert inventory.eligible(now=time.time()) == []


def test_expired_snapshot_is_rejected_without_publishing_resources():
    with tempfile.TemporaryDirectory() as directory:
        inventory = ComputeInventory(str(Path(directory) / "inventory.sqlite3"))
        registry = ComputeProviderRegistry()
        provider = Provider(snapshot(expires_at=time.time() - 1))
        registry.register(provider, domain_id="domain-a")
        fabric = ComputeFabricOrchestrator(inventory, registry=registry)
        report = fabric.refresh()
        assert report.observed[0].state == "action_required"
        assert report.eligible_resources == 0
        assert inventory.resources() == []


def test_allocate_and_release_remain_scheduler_authority():
    with tempfile.TemporaryDirectory() as directory:
        inventory = ComputeInventory(str(Path(directory) / "inventory.sqlite3"))
        registry = ComputeProviderRegistry()
        registry.register(Provider(snapshot()), domain_id="domain-a")
        fabric = ComputeFabricOrchestrator(inventory, registry=registry)
        fabric.refresh()
        requirements = ComputeRequirements(workload_class=WorkloadClass.GPU_REQUIRED, gpu=GpuRequirements(gpu_count=1))
        allocation = fabric.allocate(requirements, allocation_id="alloc-1")
        assert allocation.resource_ids == ("node-1/cpu", "node-1/0")
        assert fabric.release(allocation.resource_keys) == 2


def test_coordinator_exposes_fabric_control_plane_without_replacing_scheduler():
    from lead_engine.compute_coordinator import ComputeCoordinator
    with tempfile.TemporaryDirectory() as directory:
        coordinator = ComputeCoordinator(str(Path(directory) / "coordinator.sqlite3"), "token")
        provider = Provider(snapshot())
        coordinator.register_compute_provider(provider, domain_id="domain-a")
        report = coordinator.refresh_compute_fabric()
        assert report["eligible_resources"] == 2
        assert coordinator.compute_fabric.scheduler is coordinator.compute_scheduler
        coordinator.compute_fabric.close()


def test_controller_batch_size_is_not_a_global_backlog_cap():
    class Coordinator:
        def __init__(self):
            self.claimed = 0
        def recover_expired_tasks(self):
            return 0
        def reconcile_fabric(self):
            return {"reconciled": 0, "requeued": 0}
        def claim_physical(self):
            self.claimed += 1
            if self.claimed > 3:
                return None
            return {
                "task_id": f"task-{self.claimed}",
                "attempt_id": f"attempt-{self.claimed}",
                "generation": 1,
                "execution_identity": f"fabric:attempt-{self.claimed}",
                "physical_allocation": {},
            }

    class Fabric:
        inventory = type("Inventory", (), {"eligible": lambda self, now: []})()
        def refresh(self):
            return FabricCycleReport((), 0, 0)

    controller = ComputeFabricController(Coordinator(), fabric=Fabric())
    first = controller.cycle(max_allocations_per_cycle=2)
    second = controller.cycle(max_allocations_per_cycle=2)
    assert len(first.scheduled_allocations) == 2
    assert len(second.scheduled_allocations) == 1


def test_fault_recovery_fences_exact_generation_and_records_evidence(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator

    coordinator = ComputeCoordinator(str(Path(tmp_path) / "coordinator.sqlite3"), auth_token="token")
    task_id = coordinator.enqueue({"compute_requirements": {"workload_class": "gpu_required"}})
    attempt_id = "attempt-recovery-1"
    now = time.time()
    lease_token = "lease-recovery-1"
    import hashlib
    digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
    with coordinator._connect() as connection:
        connection.execute(
            """UPDATE compute_tasks
               SET status='leased',worker_id='fabric:attempt-recovery-1',
                   lease_token=?,lease_until=?,attempt_id=?,generation=1,attempts=1
               WHERE task_id=?""",
            (lease_token, now + 300, attempt_id, task_id),
        )
        connection.execute(
            """INSERT INTO compute_execution_attempts(
                   attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at,
                   allocation_id
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (attempt_id, task_id, 1, "fabric:attempt-recovery-1", "leased", digest, now, None),
        )
        connection.commit()

    result = coordinator.recover_compute_attempt(
        attempt_id=attempt_id,
        generation=1,
        failure_class="distributed_process_failed",
        reason="rank 3 exited non-zero",
        evidence={"rank": 3, "exit_code": 1},
    )
    assert result["status"] == "requeued"
    assert result["requeued"] is True
    assert coordinator.task(task_id)["status"] == "queued"
    assert coordinator.execution_attempt(attempt_id)["status"] == "failed"

    history = coordinator.fabric_recovery_history(attempt_id)
    assert len(history) == 1
    assert history[0]["phase"] == "fenced"
    assert history[0]["failure_class"] == "distributed_process_failed"
    assert history[0]["evidence"]["rank"] == 3

    duplicate = coordinator.recover_compute_attempt(
        attempt_id=attempt_id,
        generation=1,
        failure_class="distributed_process_failed",
        reason="duplicate stale worker report",
        evidence={"rank": 3, "exit_code": 1},
    )
    assert duplicate["status"] == "already_fenced"
    assert coordinator.task(task_id)["status"] == "queued"


def test_fault_recovery_rejects_stale_generation_without_mutating_current_task(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator

    coordinator = ComputeCoordinator(str(Path(tmp_path) / "coordinator.sqlite3"), auth_token="token")
    task_id = coordinator.enqueue({"compute_requirements": {"workload_class": "gpu_required"}})
    attempt_id = "attempt-recovery-stale"
    now = time.time()
    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_tasks SET status='queued',attempt_id=?,generation=2,updated_at=? WHERE task_id=?",
            ("new-attempt", now, task_id),
        )
        connection.execute(
            """INSERT INTO compute_execution_attempts(
                   attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (attempt_id, task_id, 1, "fabric:old", "failed", "digest", now),
        )
        connection.commit()

    result = coordinator.recover_compute_attempt(
        attempt_id=attempt_id,
        generation=1,
        failure_class="stale_worker_report",
        reason="old generation attempted recovery",
        evidence={"observed_generation": 1},
    )
    assert result["status"] == "stale_generation"
    assert coordinator.task(task_id)["attempt_id"] == "new-attempt"
    assert coordinator.task(task_id)["generation"] == 2
    history = coordinator.fabric_recovery_history(attempt_id)
    assert history[0]["phase"] == "stale_generation"


def test_recovery_supervisor_returns_stale_action_without_reallocating(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator
    from lead_engine.compute_fabric import ComputeFabricRecoverySupervisor

    coordinator = ComputeCoordinator(str(Path(tmp_path) / "coordinator.sqlite3"), auth_token="token")
    now = time.time()
    task_id = coordinator.enqueue({"compute_requirements": {"workload_class": "gpu_required"}})
    attempt_id = "attempt-supervisor-stale"
    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_tasks SET status='queued',attempt_id=?,generation=2,updated_at=? WHERE task_id=?",
            ("current-attempt", now, task_id),
        )
        connection.execute(
            """INSERT INTO compute_execution_attempts(
                   attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (attempt_id, task_id, 1, "fabric:old", "failed", "digest", now),
        )
        connection.commit()

    supervisor = ComputeFabricRecoverySupervisor(coordinator)
    action = supervisor.recover_attempt(
        attempt_id=attempt_id,
        generation=1,
        failure_class="stale_worker_report",
        reason="stale worker",
        evidence={"generation": 1},
    )
    assert action.status == "stale_generation"
    assert action.fresh_allocation_required is False
    assert coordinator.task(task_id)["generation"] == 2
