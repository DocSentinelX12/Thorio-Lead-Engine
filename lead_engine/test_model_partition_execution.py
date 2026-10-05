from lead_engine.execution_fabric_contract import ExecutionMode, ExecutionPlan
from lead_engine.model_partition_execution import ModelPartitionExecutionPlanner
from lead_engine.model_partitioning import ModelLayer, ModelPartitionPlanner


def test_partition_execution_spec_has_ordered_boundaries():
    plan = ExecutionPlan("p", "w", ExecutionMode.PIPELINE_PARALLEL, "prov", "dom", ("r0", "r1"), ("n0", "n1"), 2)
    parts = ModelPartitionPlanner().plan(plan, tuple(ModelLayer(f"l{i}", i, 1) for i in range(4)))
    spec = ModelPartitionExecutionPlanner().build(plan, parts, transport="p2p")
    assert spec.world_size == 2
    assert len(spec.boundaries) == 1
    assert spec.boundaries[0].upstream_partition_id == spec.partitions[0]
    assert spec.boundaries[0].downstream_partition_id == spec.partitions[1]


def test_observed_partition_order_is_not_fabricated():
    plan = ExecutionPlan("p", "w", ExecutionMode.P2P_MODEL_PARTITION, "prov", "dom", ("r0", "r1"), ("n0", "n1"), 2)
    parts = ModelPartitionPlanner().plan(plan, (ModelLayer("a", 0, 1), ModelLayer("b", 1, 1)))
    spec = ModelPartitionExecutionPlanner().build(plan, parts)
    ModelPartitionExecutionPlanner.validate_observed_partition_order(spec, spec.partitions)
    try:
        ModelPartitionExecutionPlanner.validate_observed_partition_order(spec, tuple(reversed(spec.partitions)))
    except ValueError as exc:
        assert "partition order" in str(exc)
    else:
        raise AssertionError("expected ValueError")
