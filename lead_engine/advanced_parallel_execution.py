"""Deterministic planning primitives for tensor, context, expert, and sharded-state execution.

Block 4 deliberately defines execution strategy, placement, partitioning, and
state ownership only. It does not implement a collective transport runtime and
does not claim physical execution evidence. NCCL integration belongs to Block 5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .execution_fabric_contract import ExecutionMode, ExecutionPlan


@dataclass(frozen=True)
class TensorShardSpec:
    tensor_id: str
    strategy: str
    shard_count: int

    def __post_init__(self) -> None:
        if not self.tensor_id.strip():
            raise ValueError("tensor_id is required")
        if self.strategy not in {"column", "row"}:
            raise ValueError("tensor strategy must be column or row")
        if self.shard_count < 1:
            raise ValueError("shard_count must be positive")


@dataclass(frozen=True)
class TensorShardPlan:
    execution_plan_id: str
    world_size: int
    rank_to_node: tuple[tuple[str, str], ...]
    shards: tuple[TensorShardSpec, ...]
    evidence_state: str = "plan_only"
    physical_execution_verified: bool = False


@dataclass(frozen=True)
class ContextPartitionSpec:
    sequence_length: int
    partition_count: int
    dimension: str = "sequence"

    def __post_init__(self) -> None:
        if self.sequence_length <= 0:
            raise ValueError("sequence_length must be positive")
        if self.partition_count <= 0:
            raise ValueError("partition_count must be positive")
        if self.dimension != "sequence":
            raise ValueError("context partition dimension must be sequence")


@dataclass(frozen=True)
class ContextParallelPlan:
    execution_plan_id: str
    partition_sizes: tuple[int, ...]
    rank_to_node: tuple[tuple[str, str], ...]
    evidence_state: str = "plan_only"
    physical_execution_verified: bool = False


@dataclass(frozen=True)
class ExpertSpec:
    expert_id: str
    rank: int

    def __post_init__(self) -> None:
        if not self.expert_id.strip():
            raise ValueError("expert_id is required")
        if self.rank < 0:
            raise ValueError("expert rank must be non-negative")


@dataclass(frozen=True)
class ExpertParallelPlan:
    execution_plan_id: str
    expert_to_rank: tuple[tuple[str, int], ...]
    rank_to_node: tuple[tuple[str, str], ...]
    evidence_state: str = "plan_only"
    physical_execution_verified: bool = False


@dataclass(frozen=True)
class ShardedStateSpec:
    parameter_bytes: int
    gradient_bytes: int
    optimizer_bytes: int
    shard_count: int
    reshard_after_forward: bool = True
    reshard_after_backward: bool = True
    checkpoint_required: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("parameter_bytes", self.parameter_bytes),
            ("gradient_bytes", self.gradient_bytes),
            ("optimizer_bytes", self.optimizer_bytes),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.shard_count <= 0:
            raise ValueError("shard_count must be positive")


@dataclass(frozen=True)
class ShardedStatePlan:
    execution_plan_id: str
    parameter_shard_bytes: tuple[int, ...]
    gradient_shard_bytes: tuple[int, ...]
    optimizer_shard_bytes: tuple[int, ...]
    owner_ranks: tuple[int, ...]
    checkpoint_compatible: bool
    reshard_after_forward: bool
    reshard_after_backward: bool
    evidence_state: str = "plan_only"
    physical_execution_verified: bool = False


class AdvancedParallelPlanner:
    """Plan Block 4 strategies without coupling them to NCCL transport."""

    @staticmethod
    def _validate_plan(plan: ExecutionPlan, mode: ExecutionMode) -> None:
        if plan.mode is not mode:
            raise ValueError(f"execution plan mode must be {mode.value}")
        if plan.worker_count < 1:
            raise ValueError("execution plan must contain workers")
        if len(plan.node_ids) != len(plan.resource_ids):
            raise ValueError("advanced parallel planning requires one resource per node")
        if plan.execution_started or plan.physical_execution_verified:
            raise ValueError("advanced parallel planner accepts plan-only execution plans")

    @staticmethod
    def _rank_to_node(plan: ExecutionPlan) -> tuple[tuple[str, str], ...]:
        return tuple((str(rank), node) for rank, node in enumerate(plan.node_ids))

    def tensor_plan(
        self, plan: ExecutionPlan, specs: Sequence[TensorShardSpec]
    ) -> TensorShardPlan:
        self._validate_plan(plan, ExecutionMode.TENSOR_PARALLEL)
        normalized = tuple(specs)
        if not normalized:
            raise ValueError("tensor shard specs are required")
        if len({spec.tensor_id for spec in normalized}) != len(normalized):
            raise ValueError("tensor IDs must be unique")
        world_size = plan.worker_count
        for spec in normalized:
            if spec.shard_count != world_size:
                raise ValueError("tensor shard count must equal world size")
        return TensorShardPlan(plan.plan_id, world_size, self._rank_to_node(plan), normalized)

    def context_plan(
        self, plan: ExecutionPlan, spec: ContextPartitionSpec
    ) -> ContextParallelPlan:
        self._validate_plan(plan, ExecutionMode.CONTEXT_PARALLEL)
        if spec.partition_count != plan.worker_count:
            raise ValueError("context partition count must equal worker count")
        if spec.sequence_length % spec.partition_count:
            raise ValueError("sequence length must be divisible by partition count")
        size = spec.sequence_length // spec.partition_count
        return ContextParallelPlan(
            plan.plan_id,
            (size,) * spec.partition_count,
            self._rank_to_node(plan),
        )

    def expert_plan(
        self, plan: ExecutionPlan, experts: Sequence[ExpertSpec]
    ) -> ExpertParallelPlan:
        self._validate_plan(plan, ExecutionMode.EXPERT_PARALLEL)
        normalized = tuple(sorted(experts, key=lambda item: (item.rank, item.expert_id)))
        if not normalized:
            raise ValueError("expert specs are required")
        if len({expert.expert_id for expert in normalized}) != len(normalized):
            raise ValueError("expert IDs must be unique")
        if any(expert.rank >= plan.worker_count for expert in normalized):
            raise ValueError("expert rank is outside execution world size")
        return ExpertParallelPlan(
            plan.plan_id,
            tuple((expert.expert_id, expert.rank) for expert in normalized),
            self._rank_to_node(plan),
        )

    def sharded_state_plan(
        self, plan: ExecutionPlan, spec: ShardedStateSpec
    ) -> ShardedStatePlan:
        self._validate_plan(plan, ExecutionMode.SHARDED_STATE)
        if spec.shard_count != plan.worker_count:
            raise ValueError("state shard count must equal worker count")
        values = (spec.parameter_bytes, spec.gradient_bytes, spec.optimizer_bytes)
        names = ("parameter", "gradient", "optimizer")
        shards: list[tuple[int, ...]] = []
        for name, value in zip(names, values):
            if value % spec.shard_count:
                raise ValueError(f"{name} bytes must be divisible by shard count")
            shards.append((value // spec.shard_count,) * spec.shard_count)
        if spec.checkpoint_required is False:
            checkpoint_compatible = False
        else:
            checkpoint_compatible = True
        return ShardedStatePlan(
            plan.plan_id,
            shards[0],
            shards[1],
            shards[2],
            tuple(range(spec.shard_count)),
            checkpoint_compatible,
            spec.reshard_after_forward,
            spec.reshard_after_backward,
        )
