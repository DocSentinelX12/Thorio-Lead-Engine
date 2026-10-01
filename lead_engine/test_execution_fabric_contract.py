from __future__ import annotations

import pytest

from lead_engine.execution_fabric_contract import (
    ExecutionCapability,
    ExecutionMode,
    ExecutionPlanner,
    ExecutionWorkload,
)


def _capability(*modes: ExecutionMode, verified: bool = True) -> ExecutionCapability:
    return ExecutionCapability(
        resource_ids=("node-a/gpu-0",),
        node_ids=("node-a",),
        provider_id="provider-a",
        domain_id="domain-a",
        supported_modes=tuple(modes),
        physical_gpu_verified=verified,
    )


def test_execution_mode_vocabulary_covers_the_fabric_families():
    assert {mode.value for mode in ExecutionMode} == {
        "single_gpu",
        "batch_parallel",
        "data_parallel",
        "pipeline_parallel",
        "tensor_parallel",
        "context_parallel",
        "expert_parallel",
        "sharded_state",
        "p2p_model_partition",
        "nccl",
        "hybrid",
    }


def test_execution_workload_requires_explicit_modes_and_preserves_order():
    workload = ExecutionWorkload(
        workload_id="job-1",
        allowed_modes=(ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.SINGLE_GPU),
        min_workers=1,
        max_workers=4,
        checkpoint_required=True,
        elastic=True,
    )

    assert workload.allowed_modes == (
        ExecutionMode.PIPELINE_PARALLEL,
        ExecutionMode.SINGLE_GPU,
    )
    assert workload.checkpoint_required is True
    assert workload.elastic is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"workload_id": "", "allowed_modes": (ExecutionMode.SINGLE_GPU,)},
        {"workload_id": "job-1", "allowed_modes": ()},
        {"workload_id": "job-1", "allowed_modes": (ExecutionMode.SINGLE_GPU,), "min_workers": 0},
        {"workload_id": "job-1", "allowed_modes": (ExecutionMode.SINGLE_GPU,), "min_workers": 2, "max_workers": 1},
    ],
)
def test_execution_workload_rejects_invalid_contract(kwargs):
    with pytest.raises(ValueError):
        ExecutionWorkload(**kwargs)


def test_planner_selects_first_supported_mode_without_claiming_execution():
    workload = ExecutionWorkload(
        workload_id="job-1",
        allowed_modes=(ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.SINGLE_GPU),
        min_workers=1,
        max_workers=1,
    )
    capability = _capability(ExecutionMode.SINGLE_GPU)

    plan = ExecutionPlanner().plan(workload, (capability,))

    assert plan.mode is ExecutionMode.SINGLE_GPU
    assert plan.resource_ids == ("node-a/gpu-0",)
    assert plan.node_ids == ("node-a",)
    assert plan.execution_started is False
    assert plan.physical_execution_verified is False


def test_planner_rejects_mode_without_capability_support():
    workload = ExecutionWorkload(
        workload_id="job-1",
        allowed_modes=(ExecutionMode.NCCL,),
        min_workers=2,
        max_workers=2,
    )
    capability = _capability(ExecutionMode.SINGLE_GPU)

    with pytest.raises(ValueError, match="no supported execution mode"):
        ExecutionPlanner().plan(workload, (capability,))


def test_planner_requires_physical_verification_for_gpu_execution():
    workload = ExecutionWorkload(
        workload_id="job-1",
        allowed_modes=(ExecutionMode.SINGLE_GPU,),
    )
    capability = _capability(ExecutionMode.SINGLE_GPU, verified=False)

    with pytest.raises(ValueError, match="physical GPU verification"):
        ExecutionPlanner().plan(workload, (capability,))
