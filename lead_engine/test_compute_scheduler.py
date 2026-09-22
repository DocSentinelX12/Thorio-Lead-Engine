import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_resources import (
    ComputeRequirements,
    CpuResource,
    GpuRequirements,
    GpuResource,
    NodeResource,
    ResourceState,
    WorkloadClass,
)
from lead_engine.compute_scheduler import ComputeScheduler, ComputeSchedulingError
from lead_engine.compute_provider import ProviderResourceSnapshot


def _gpu(node, gpu, **kwargs):
    return GpuResource(node_id=node, gpu_id=gpu, **kwargs)


def _snapshot(nodes):
    return ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=tuple(nodes),
        authentication_state="authenticated",
        evidence={"source": "scheduler-test"},
    )


def _node(node_id, gpus, *, cpu_count=32, memory_bytes=128 * 1024**3, cuda="12.4", driver="550.54", nccl="2.21"):
    return NodeResource(
        node_id=node_id,
        architecture="x86_64",
        cpu=CpuResource(node_id, cpu_count, memory_bytes),
        gpus=tuple(gpus),
        cuda_version=cuda,
        driver_version=driver,
        nccl_version=nccl,
        state=ResourceState.AVAILABLE,
    )


def _ready_gpu(node, gpu, **kwargs):
    return _gpu(
        node, gpu,
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
        **kwargs,
    )


def test_four_gpu_request_uses_four_concrete_gpus(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", vram_bytes=24 * 1024**3),
        _ready_gpu("node-a", "gpu-1", gpu_uuid="u1", vram_bytes=24 * 1024**3),
        _ready_gpu("node-a", "gpu-2", gpu_uuid="u2", vram_bytes=24 * 1024**3),
        _ready_gpu("node-a", "gpu-3", gpu_uuid="u3", vram_bytes=24 * 1024**3),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.MULTI_GPU, GpuRequirements(gpu_count=4, min_vram_bytes=24 * 1024**3)),
        "allocation-1",
    )
    assert len([r for r in allocation.resource_ids if "/gpu-" in r]) == 4
    assert len(allocation.node_ids) == 1
    assert all(inventory.get(key)["state"] == ResourceState.RESERVED.value for key in allocation.resource_keys)


def test_one_large_gpu_cannot_satisfy_four_gpu_request(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", vram_bytes=96 * 1024**3),
    ])]))
    with pytest.raises(ComputeSchedulingError):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(WorkloadClass.MULTI_GPU, GpuRequirements(gpu_count=4, min_vram_bytes=24 * 1024**3)),
            "allocation-1",
        )


def test_cuda_mismatch_is_rejected(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", vram_bytes=24 * 1024**3, cuda_version="11.8"),
    ])]))
    with pytest.raises(ComputeSchedulingError):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1, required_cuda_version="12.0")),
            "allocation-1",
        )


def test_unauthenticated_resources_are_not_admitted(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(_node("node-a", [
            _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
        ]),),
        authentication_state="unauthenticated",
    ))
    assert inventory.eligible() == []
    with pytest.raises(ComputeSchedulingError):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
            "allocation-unauthenticated",
        )


def test_quarantined_gpu_is_excluded(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", vram_bytes=24 * 1024**3),
    ])]))
    key = "provider-a/domain-a/node-a/gpu/u0"
    inventory.mark_state(key, ResourceState.QUARANTINED)
    with pytest.raises(ComputeSchedulingError):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
            "allocation-1",
        )


def test_multi_gpu_prefers_verified_topology_domain_concentration(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", topology_domain="weak"),
        _ready_gpu("node-a", "gpu-1", gpu_uuid="u1", topology_domain="weak"),
        _ready_gpu("node-a", "gpu-2", gpu_uuid="strong"),
        _ready_gpu("node-a", "gpu-3", gpu_uuid="strong"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.MULTI_GPU, GpuRequirements(gpu_count=2, require_nccl=True)),
        "allocation-topology",
    )
    assert allocation.resource_ids == ("node-a/cpu", "node-a/gpu-2", "node-a/gpu-3")


def test_multi_gpu_does_not_claim_topology_locality_when_domains_are_disconnected(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", topology_domain="domain-a"),
        _ready_gpu("node-a", "gpu-1", gpu_uuid="u1", topology_domain="domain-b"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.MULTI_GPU, GpuRequirements(gpu_count=2, require_nccl=True)),
        "allocation-disconnected",
    )
    assert allocation.resource_ids == ("node-a/cpu", "node-a/gpu-0", "node-a/gpu-1")
    assert {e["topology_domain"] for e in allocation.capability_evidence if e.get("resource_type") != "cpu"} == {"domain-a", "domain-b"}


def test_topology_domain_is_enforced(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0", topology_domain="wrong"),
        _ready_gpu("node-a", "gpu-1", gpu_uuid="u1", topology_domain="right"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1), topology_domain="right"),
        "allocation-1",
    )
    assert allocation.resource_ids == ("node-a/cpu", "node-a/gpu-1")


def test_multi_node_request_spans_nodes(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([
        _node("node-a", [_ready_gpu("node-a", "gpu-0", gpu_uuid="u0", vram_bytes=24 * 1024**3)]),
        _node("node-b", [_ready_gpu("node-b", "gpu-0", gpu_uuid="u1", vram_bytes=24 * 1024**3)]),
    ]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(
            WorkloadClass.MULTI_NODE_GPU,
            GpuRequirements(gpu_count=2),
            same_node=False,
        ),
        "allocation-1",
    )
    assert set(allocation.node_ids) == {"node-a", "node-b"}


def test_cpu_only_work_does_not_consume_gpu(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.CPU_BOUND),
        "allocation-1",
    )
    assert allocation.resource_ids == ("node-a/cpu",)
    assert inventory.get("provider-a/domain-a/node-a/gpu/u0")["state"] == ResourceState.AVAILABLE.value


def test_failed_allocation_leaves_inventory_unchanged(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [])]))
    with pytest.raises(ComputeSchedulingError):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
            "allocation-1",
        )
    assert inventory.get("provider-a/domain-a/node-a/cpu")["state"] == ResourceState.AVAILABLE.value


def test_release_returns_reserved_resources_to_available(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    scheduler = ComputeScheduler(inventory)
    allocation = scheduler.allocate(ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)), "allocation-1")
    assert scheduler.release(allocation.resource_keys) == 2
    assert all(inventory.get(key)["state"] == ResourceState.AVAILABLE.value for key in allocation.resource_keys)


def test_second_allocation_cannot_double_book_reserved_gpu(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    scheduler = ComputeScheduler(inventory)
    scheduler.allocate(ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)), "allocation-1")
    with pytest.raises(ComputeSchedulingError):
        scheduler.allocate(ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)), "allocation-2")


def test_concurrent_allocations_cannot_double_book_a_physical_gpu(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    scheduler = ComputeScheduler(inventory)
    requirements = ComputeRequirements(
        WorkloadClass.GPU_REQUIRED,
        GpuRequirements(gpu_count=1),
    )

    def allocate(index):
        try:
            return ("ok", scheduler.allocate(requirements, f"concurrent-{index}"))
        except ComputeSchedulingError:
            return ("rejected", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(allocate, range(2)))

    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("rejected") == 1
    allocations = inventory.allocations(state="reserved")
    assert len(allocations) == 1
    assert set(allocations[0]["resource_keys"]) == {"provider-a/domain-a/node-a/gpu/u0", "provider-a/domain-a/node-a/cpu"}


def test_allocation_has_durable_owner_record(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
        "allocation-1",
    )
    stored = inventory.allocation("allocation-1")
    assert stored["state"] == "reserved"
    assert stored["task_id"] is None
    assert set(stored["resource_keys"]) == set(allocation.resource_keys)


def test_allocation_binding_is_idempotent_and_generation_specific(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
        "allocation-1",
    )
    assert inventory.bind_allocation(
        "allocation-1", task_id="task-1", attempt_id="attempt-1",
        generation=1, lease_token_digest="digest-1",
    )
    assert inventory.bind_allocation(
        "allocation-1", task_id="task-1", attempt_id="attempt-1",
        generation=1, lease_token_digest="digest-1",
    )
    assert not inventory.bind_allocation(
        "allocation-1", task_id="task-1", attempt_id="attempt-2",
        generation=2, lease_token_digest="digest-2",
    )
    stored = inventory.allocation("allocation-1")
    assert stored["state"] == "bound"
    assert stored["attempt_id"] == "attempt-1"
    assert stored["generation"] == 1


def test_stale_generation_cannot_release_newer_binding(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    scheduler = ComputeScheduler(inventory)
    allocation = scheduler.allocate(
        ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
        "allocation-1",
    )
    assert inventory.bind_allocation(
        allocation.allocation_id, task_id="task-1", attempt_id="attempt-1",
        generation=2, lease_token_digest="digest-2",
    )
    assert inventory.release_allocation(
        allocation.allocation_id, task_id="task-1", attempt_id="attempt-1",
        generation=1, reason="stale recovery",
    ) == 0
    assert inventory.get(allocation.resource_keys[-1])["state"] == ResourceState.RESERVED.value
    assert inventory.release_allocation(
        allocation.allocation_id, task_id="task-1", attempt_id="attempt-1",
        generation=2, reason="completed",
    ) == 2
    assert inventory.get(allocation.resource_keys[-1])["state"] == ResourceState.AVAILABLE.value


def test_provider_missing_does_not_erase_reserved_allocation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot([_node("node-a", [
        _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
    ])]))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.GPU_REQUIRED, GpuRequirements(gpu_count=1)),
        "allocation-1",
    )
    assert inventory.mark_provider_missing("provider-a", "domain-a") == 0
    assert inventory.get(allocation.resource_keys[-1])["state"] == ResourceState.RESERVED.value


def test_twelve_node_request_is_not_artificially_capped(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    nodes = [
        _node(f"node-{index:02d}", [_ready_gpu(f"node-{index:02d}", "gpu-0", gpu_uuid=f"u{index}", vram_bytes=24 * 1024**3)])
        for index in range(12)
    ]
    inventory.observe(_snapshot(nodes))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.MULTI_NODE_GPU, GpuRequirements(gpu_count=12), same_node=False),
        "allocation-12",
    )
    assert len(allocation.node_ids) == 12
    assert len([resource for resource in allocation.resource_ids if "/gpu-" in resource]) == 12


def test_five_hundred_gpu_request_has_no_fixed_resource_ceiling(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    nodes = [
        _node(f"node-{index:03d}", [_ready_gpu(f"node-{index:03d}", "gpu-0", gpu_uuid=f"u{index}", vram_bytes=24 * 1024**3)])
        for index in range(500)
    ]
    inventory.observe(_snapshot(nodes))
    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(WorkloadClass.MULTI_NODE_GPU, GpuRequirements(gpu_count=500), same_node=False),
        "allocation-500",
    )
    assert len(allocation.node_ids) == 500
    assert len([resource for resource in allocation.resource_ids if "/gpu-" in resource]) == 500


def test_multi_node_allocation_does_not_cross_provider_or_domain_boundary(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-a", domain_id="domain-a", observed_at=time.time(),
        nodes=(_node("node-a", [_ready_gpu("node-a", "gpu-0", gpu_uuid="u-a")]),),
        authentication_state="authenticated",
    ))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-b", domain_id="domain-b", observed_at=time.time(),
        nodes=(_node("node-b", [_ready_gpu("node-b", "gpu-0", gpu_uuid="u-b")]),),
        authentication_state="authenticated",
    ))
    with pytest.raises(ComputeSchedulingError, match="provider and domain"):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(WorkloadClass.MULTI_NODE_GPU, GpuRequirements(gpu_count=2), same_node=False),
            "allocation-cross-boundary",
        )


def test_expired_resource_cannot_be_reserved_from_a_stale_candidate_snapshot(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        expires_at=time.time() + 0.05,
        ephemeral=True,
        nodes=(_node("node-a", [
            _ready_gpu("node-a", "gpu-0", gpu_uuid="u0"),
        ]),),
        authentication_state="authenticated",
    ))
    time.sleep(0.08)
    row = inventory.get("provider-a/domain-a/node-a/gpu/u0")
    with pytest.raises(ValueError, match="no longer available"):
        inventory.reserve_allocation(
            "allocation-expired",
            "provider-a",
            "domain-a",
            ("provider-a/domain-a/node-a/gpu/u0",),
        )
    assert row["state"] == ResourceState.AVAILABLE.value
