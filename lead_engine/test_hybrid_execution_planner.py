from lead_engine.execution_fabric_contract import ExecutionCapability, ExecutionMode, ExecutionPlan
from lead_engine.hybrid_execution_planner import HybridExecutionPlanner


def test_hybrid_pipeline_and_tensor_plan():
    plan = ExecutionPlan(
        "hp", "w", ExecutionMode.HYBRID, "p", "d", ("r0","r1"), ("n0","n1"), 2
    )
    caps = (
        ExecutionCapability(("r0",), ("n0",), "p", "d",
            (ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.TENSOR_PARALLEL), True, backends=("nccl",)),
        ExecutionCapability(("r1",), ("n1",), "p", "d",
            (ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.TENSOR_PARALLEL), True, backends=("nccl",)),
    )
    result = HybridExecutionPlanner().plan(
        plan, (ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.TENSOR_PARALLEL), caps)
    assert result.stages == (ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.TENSOR_PARALLEL)


def test_hybrid_rejects_tight_stage_without_nccl():
    plan = ExecutionPlan("hp", "w", ExecutionMode.HYBRID, "p", "d", ("r0","r1"), ("n0","n1"), 2)
    caps = (
        ExecutionCapability(("r0",), ("n0",), "p", "d", (ExecutionMode.TENSOR_PARALLEL,), True, backends=("gloo",)),
        ExecutionCapability(("r1",), ("n1",), "p", "d", (ExecutionMode.TENSOR_PARALLEL,), True, backends=("gloo",)),
    )
    try:
        HybridExecutionPlanner().plan(plan, (ExecutionMode.TENSOR_PARALLEL,), caps)
    except ValueError as exc:
        assert "NCCL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_hybrid_rejects_single_gpu_mixed_with_distributed_stage():
    plan = ExecutionPlan("hp2", "w", ExecutionMode.HYBRID, "p", "d", ("r0","r1"), ("n0","n1"), 2)
    caps = (
        ExecutionCapability(("r0",), ("n0",), "p", "d",
            (ExecutionMode.SINGLE_GPU, ExecutionMode.DATA_PARALLEL), True),
        ExecutionCapability(("r1",), ("n1",), "p", "d",
            (ExecutionMode.SINGLE_GPU, ExecutionMode.DATA_PARALLEL), True),
    )
    try:
        HybridExecutionPlanner().plan(
            plan, (ExecutionMode.SINGLE_GPU, ExecutionMode.DATA_PARALLEL), caps)
    except ValueError as exc:
        assert "single_gpu" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_hybrid_allows_context_tensor_composition_with_required_transport():
    plan = ExecutionPlan("hp3", "w", ExecutionMode.HYBRID, "p", "d", ("r0","r1"), ("n0","n1"), 2)
    caps = (
        ExecutionCapability(("r0",), ("n0",), "p", "d",
            (ExecutionMode.CONTEXT_PARALLEL, ExecutionMode.TENSOR_PARALLEL), True, backends=("nccl",)),
        ExecutionCapability(("r1",), ("n1",), "p", "d",
            (ExecutionMode.CONTEXT_PARALLEL, ExecutionMode.TENSOR_PARALLEL), True, backends=("nccl",)),
    )
    result = HybridExecutionPlanner().plan(
        plan, (ExecutionMode.CONTEXT_PARALLEL, ExecutionMode.TENSOR_PARALLEL), caps)
    assert result.stages == (ExecutionMode.CONTEXT_PARALLEL, ExecutionMode.TENSOR_PARALLEL)
