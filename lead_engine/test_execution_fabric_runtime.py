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
