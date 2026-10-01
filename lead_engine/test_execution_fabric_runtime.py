from lead_engine.execution_fabric_runtime import ProductionExecutionFabric
from lead_engine.execution_fabric_contract import ExecutionMode


def _allocation(count=2):
    return {
        "provider_id": "provider",
        "domain_id": "domain",
        "resource_ids": tuple(f"node-{i}/gpu/{i}" for i in range(count)),
        "node_ids": tuple(f"node-{i}" for i in range(count)),
        "capability_evidence": tuple(
            {"resource_id": f"node-{i}/gpu/{i}", "gpu_id": str(i), "gpu_uuid": f"GPU-{i}"}
            for i in range(count)
        ),
    }


def test_integrated_tensor_plan_uses_universal_contract():
    result = ProductionExecutionFabric().plan(
        {
            "workload_id": "w1",
            "execution_mode": ExecutionMode.TENSOR_PARALLEL.value,
            "tensor_shards": [
                {"tensor_id": "t0", "strategy": "column", "shard_count": 2}
            ],
        },
        _allocation(),
    )
    assert result.execution_plan.mode is ExecutionMode.TENSOR_PARALLEL
    assert result.execution_plan.evidence_state == "plan_only"
    assert "tensor_shard_plan" in result.mode_details


def test_integrated_single_gpu_plan_allows_one_resource():
    allocation = _allocation(1)
    result = ProductionExecutionFabric().plan(
        {"workload_id": "w1", "execution_mode": "single_gpu"},
        allocation,
    )
    assert result.execution_plan.worker_count == 1


def test_integrated_pipeline_plan_uses_model_partition_planner():
    result = ProductionExecutionFabric().plan(
        {
            "workload_id": "w1",
            "execution_mode": "pipeline_parallel",
            "model_layers": [
                {"layer_id": "l0", "ordinal": 0, "parameter_bytes": 10},
                {"layer_id": "l1", "ordinal": 1, "parameter_bytes": 10},
            ],
        },
        _allocation(),
    )
    assert "model_partition_plan" in result.mode_details


def test_integrated_planning_never_claims_execution():
    result = ProductionExecutionFabric().plan(
        {"workload_id": "w1", "execution_mode": "data_parallel"},
        _allocation(),
    )
    assert result.execution_plan.physical_execution_verified is False


def test_integrated_context_expert_sharded_and_nccl_plans():
    fabric = ProductionExecutionFabric()
    context = fabric.plan(
        {
            "workload_id": "context",
            "execution_mode": "context_parallel",
            "context_partition": {"sequence_length": 1024, "partition_count": 2},
        },
        _allocation(),
    )
    assert "context_partition_plan" in context.mode_details

    expert = fabric.plan(
        {
            "workload_id": "expert",
            "execution_mode": "expert_parallel",
            "experts": [{"expert_id": "e0", "rank": 0}, {"expert_id": "e1", "rank": 1}],
        },
        _allocation(),
    )
    assert "expert_parallel_plan" in expert.mode_details

    sharded = fabric.plan(
        {
            "workload_id": "sharded",
            "execution_mode": "sharded_state",
            "sharded_state": {
                "parameter_bytes": 100,
                "gradient_bytes": 100,
                "optimizer_bytes": 100,
                "shard_count": 2,
            },
        },
        _allocation(),
    )
    assert "sharded_state_plan" in sharded.mode_details

    nccl = fabric.plan(
        {
            "workload_id": "nccl",
            "execution_mode": "nccl",
            "nccl_launch": {"collective": "all_reduce"},
        },
        _allocation(),
        rendezvous_endpoint="10.0.0.1:29500",
    )
    assert nccl.mode_details["nccl_execution_plan"]["master_addr"] == "10.0.0.1"


def test_integrated_hybrid_plan_validates_composed_stage_capabilities():
    result = ProductionExecutionFabric().plan(
        {
            "workload_id": "hybrid",
            "execution_mode": "hybrid",
            "hybrid_stages": ["data_parallel", "pipeline_parallel"],
        },
        _allocation(),
    )
    assert tuple(result.mode_details["hybrid_execution_plan"]["stages"]) == (
        ExecutionMode.DATA_PARALLEL,
        ExecutionMode.PIPELINE_PARALLEL,
    )


def test_legacy_gpu_payload_defaults_to_single_gpu_mode():
    result = ProductionExecutionFabric().plan(
        {"task_id": "legacy-gpu", "kind": "gpu_workload"},
        _allocation(1),
    )
    assert result.execution_plan.mode is ExecutionMode.SINGLE_GPU


def test_legacy_nccl_requirement_defaults_to_nccl_mode():
    result = ProductionExecutionFabric().plan(
        {
            "task_id": "legacy-nccl",
            "compute_requirements": {"gpu": {"gpu_count": 2, "require_nccl": True}},
        },
        _allocation(),
        rendezvous_endpoint="10.0.0.1:29500",
    )
    assert result.execution_plan.mode is ExecutionMode.NCCL
