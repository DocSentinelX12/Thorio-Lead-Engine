import time

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
