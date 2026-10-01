from lead_engine.advanced_parallel_execution import (
    AdvancedParallelPlanner,
    ExpertSpec,
    ShardedStateSpec,
    TensorShardSpec,
    ContextPartitionSpec,
)
from lead_engine.execution_fabric_contract import ExecutionMode, ExecutionPlan


def _plan(mode):
    return ExecutionPlan(
        "plan-advanced", "workload-advanced", mode, "provider", "domain",
        ("gpu0", "gpu1", "gpu2", "gpu3"),
        ("node0", "node1", "node2", "node3"), 4,
    )


def test_tensor_parallel_builds_deterministic_rank_shards():
    result = AdvancedParallelPlanner().tensor_plan(
        _plan(ExecutionMode.TENSOR_PARALLEL),
        (TensorShardSpec("attention.q", "column", 4),
         TensorShardSpec("attention.o", "row", 4)),
    )
    assert result.world_size == 4
    assert result.rank_to_node == (("0", "node0"), ("1", "node1"), ("2", "node2"), ("3", "node3"))
    assert result.shards[0].shard_count == 4
    assert result.shards[1].strategy == "row"


def test_tensor_parallel_rejects_non_divisible_shard_count():
    try:
        AdvancedParallelPlanner().tensor_plan(
            _plan(ExecutionMode.TENSOR_PARALLEL),
            (TensorShardSpec("layer", "column", 2),),
        )
    except ValueError as exc:
        assert "world size" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_context_parallel_partitions_sequence_without_physical_claims():
    result = AdvancedParallelPlanner().context_plan(
        _plan(ExecutionMode.CONTEXT_PARALLEL),
        ContextPartitionSpec(sequence_length=1024, partition_count=4, dimension="sequence"),
    )
    assert result.partition_sizes == (256, 256, 256, 256)
    assert result.physical_execution_verified is False


def test_context_parallel_rejects_non_divisible_sequence():
    try:
        AdvancedParallelPlanner().context_plan(
            _plan(ExecutionMode.CONTEXT_PARALLEL),
            ContextPartitionSpec(sequence_length=1000, partition_count=4, dimension="sequence"),
        )
    except ValueError as exc:
        assert "divisible" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_expert_parallel_assigns_each_expert_once():
    result = AdvancedParallelPlanner().expert_plan(
        _plan(ExecutionMode.EXPERT_PARALLEL),
        (ExpertSpec("e0", 0), ExpertSpec("e1", 1), ExpertSpec("e2", 2), ExpertSpec("e3", 3)),
    )
    assert result.expert_to_rank == (("e0", 0), ("e1", 1), ("e2", 2), ("e3", 3))


def test_expert_parallel_rejects_invalid_rank():
    try:
        AdvancedParallelPlanner().expert_plan(
            _plan(ExecutionMode.EXPERT_PARALLEL),
            (ExpertSpec("e0", 4),),
        )
    except ValueError as exc:
        assert "rank" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_sharded_state_plans_parameter_gradient_and_optimizer_ownership():
    result = AdvancedParallelPlanner().sharded_state_plan(
        _plan(ExecutionMode.SHARDED_STATE),
        ShardedStateSpec(parameter_bytes=1000, gradient_bytes=600, optimizer_bytes=800, shard_count=4),
    )
    assert result.parameter_shard_bytes == (250, 250, 250, 250)
    assert result.gradient_shard_bytes == (150, 150, 150, 150)
    assert result.optimizer_shard_bytes == (200, 200, 200, 200)
    assert result.checkpoint_compatible is True


def test_sharded_state_requires_divisible_state_sizes():
    try:
        AdvancedParallelPlanner().sharded_state_plan(
            _plan(ExecutionMode.SHARDED_STATE),
            ShardedStateSpec(parameter_bytes=1001, gradient_bytes=600, optimizer_bytes=800, shard_count=4),
        )
    except ValueError as exc:
        assert "divisible" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_advanced_plans_are_not_execution_evidence():
    result = AdvancedParallelPlanner().tensor_plan(
        _plan(ExecutionMode.TENSOR_PARALLEL),
        (TensorShardSpec("layer", "column", 4),),
    )
    assert result.physical_execution_verified is False
    assert result.evidence_state == "plan_only"
