from lead_engine.compute_resources import (
    ComputeRequirements,
    CpuResource,
    GpuRequirements,
    GpuResource,
    NodeResource,
    ResourceLease,
    ResourceState,
    WorkloadClass,
)


def _gpu(node, gpu, **kwargs):
    return GpuResource(node_id=node, gpu_id=gpu, **kwargs)


def test_gpu_is_independently_addressable():
    gpu = _gpu("node-a", "gpu-000", gpu_uuid="UUID-1", vram_bytes=24 * 1024**3)
    assert gpu.resource_id == "node-a/gpu-000"
    assert gpu.identity_key == "UUID-1"


def test_missing_gpu_uuid_does_not_get_fabricated():
    gpu = _gpu("node-a", "gpu-000")
    assert gpu.gpu_uuid is None
    assert gpu.identity_key == "node-a/gpu-000"


def test_node_contains_concrete_gpu_resources():
    cpu = CpuResource("node-a", 32, 128 * 1024**3)
    node = NodeResource("node-a", "x86_64", cpu, (
        _gpu("node-a", "gpu-0"),
        _gpu("node-a", "gpu-1"),
    ))
    assert node.gpu_count == 2
    assert {gpu.resource_id for gpu in node.gpus} == {"node-a/gpu-0", "node-a/gpu-1"}


def test_multi_gpu_requirement_is_concrete_gpu_count():
    requirements = ComputeRequirements(
        workload_class=WorkloadClass.MULTI_GPU,
        gpu=GpuRequirements(gpu_count=8, min_vram_bytes=24 * 1024**3),
    )
    assert requirements.gpu.gpu_count == 8


def test_nccL_is_not_required_for_single_gpu():
    requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        gpu=GpuRequirements(gpu_count=1),
    )
    assert requirements.gpu.require_nccL is False


def test_multi_node_gpu_cannot_claim_same_node():
    try:
        ComputeRequirements(
            workload_class=WorkloadClass.MULTI_NODE_GPU,
            gpu=GpuRequirements(gpu_count=8, require_nccL=True),
            same_node=True,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid multi-node same-node requirement was accepted")


def test_lease_requires_unique_concrete_resources():
    try:
        ResourceLease("lease-1", "task-1", 1, ("node-a/gpu-0", "node-a/gpu-0"), 100.0)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate GPU resource IDs were accepted")
