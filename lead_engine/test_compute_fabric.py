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

        requirements = ComputeRequirements(
            workload_class=WorkloadClass.GPU_REQUIRED,
            gpu=GpuRequirements(gpu_count=1),
        )
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


def test_controller_cycles_durable_gpu_work_into_physical_execution_assignments():
    from lead_engine.compute_coordinator import ComputeCoordinator
    from lead_engine.compute_pool import WorkerIdentity

    with tempfile.TemporaryDirectory() as directory:
        coordinator = ComputeCoordinator(str(Path(directory) / "coordinator.sqlite3"), "token")
        gpu = GpuResource(
            node_id="worker-1", gpu_id="0", gpu_uuid="GPU-worker-1", model="NVIDIA H100",
            vram_bytes=80 * 1024**3, compute_capability="9.0",
            health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
        )
        coordinator.register_worker(WorkerIdentity(
            worker_id="worker-1", hostname="worker-1", architecture="x86_64",
            cpu_count=32, memory_mb=131072, capabilities=("lead_prepare",),
            gpu_resources=(gpu,), driver_version="550", cuda_version="12.4",
            nccl_version="2.20", nic_names=("eth0",), gpu_discovery_state="verified",
            gpu_discovery_error="",
        ))
        task_id = coordinator.enqueue({
            "kind": "agent_task", "agent": "lead_prepare",
            "compute_requirements": {"workload_class": "gpu_required", "gpu": {"gpu_count": 1}},
        })
        controller = ComputeFabricController(coordinator)

        cycle = controller.cycle(max_allocations_per_cycle=1)

        assert cycle.refresh.scheduled_allocations == 1
        assert cycle.scheduled_allocations[0]["task_id"] == task_id
        task = coordinator.task(task_id)
        assert task is not None and task["status"] == "leased"
        assert coordinator.execution_participants(task["attempt_id"])[0]["worker_id"] == "worker-1"
        coordinator.release("fabric:" + task["attempt_id"], task_id, task["lease_token"], "test cleanup")


def test_controller_batch_size_is_not_a_global_backlog_cap():
    class Coordinator:
        def __init__(self):
            self.compute_fabric = object()
            self.claimed = 0
        def recover_expired_tasks(self): return 0
        def reconcile_fabric(self): return {"reconciled": 0, "requeued": 0}
        def claim_physical(self):
            self.claimed += 1
            return None if self.claimed > 3 else {
                "task_id": f"task-{self.claimed}", "attempt_id": f"attempt-{self.claimed}",
                "generation": 1, "execution_identity": f"fabric:attempt-{self.claimed}",
                "physical_allocation": {},
            }

    class Fabric:
        inventory = type("Inventory", (), {"eligible": lambda self, now: []})()
        def refresh(self): return FabricCycleReport((), 0, 0)

    coordinator = Coordinator()
    controller = ComputeFabricController(coordinator, fabric=Fabric())
    first = controller.cycle(max_allocations_per_cycle=2)
    second = controller.cycle(max_allocations_per_cycle=2)

    assert len(first.scheduled_allocations) == 2
    assert len(second.scheduled_allocations) == 1
