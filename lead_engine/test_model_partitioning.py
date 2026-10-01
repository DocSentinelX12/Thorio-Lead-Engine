from lead_engine.execution_fabric_contract import ExecutionMode, ExecutionPlan
from lead_engine.model_partitioning import ModelLayer, ModelPartitionPlanner


def _plan(mode=ExecutionMode.PIPELINE_PARALLEL):
    return ExecutionPlan(
        plan_id="plan-1", workload_id="w-1", mode=mode,
        provider_id="p", domain_id="d", resource_ids=("r1","r2"),
        node_ids=("n1","n2"), worker_count=2,
    )


def test_pipeline_partition_is_deterministic():
    layers = tuple(ModelLayer(f"l{i}", i, 10 if i < 2 else 30) for i in range(4))
    result = ModelPartitionPlanner().plan(_plan(), layers)
    assert result.boundary_count == 1
    assert sum(len(p.layer_ids) for p in result.partitions) == 4
    assert result.partitions[0].partition_id.startswith("plan-1:partition:")


def test_p2p_partition_uses_same_contract():
    result = ModelPartitionPlanner().plan(_plan(ExecutionMode.P2P_MODEL_PARTITION),
        (ModelLayer("a", 0, 1), ModelLayer("b", 1, 2)))
    assert result.mode is ExecutionMode.P2P_MODEL_PARTITION


def test_partition_rejects_non_contiguous_layers():
    try:
        ModelPartitionPlanner().plan(_plan(), (ModelLayer("a", 0, 1), ModelLayer("b", 2, 1)))
    except ValueError as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("expected ValueError")
