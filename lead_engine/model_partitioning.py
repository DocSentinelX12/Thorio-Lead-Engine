"""Deterministic model partitioning plans for pipeline and P2P execution.

Planning only: this module assigns model layers to already-verified workers.
It never starts execution or claims physical evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .execution_fabric_contract import ExecutionMode, ExecutionPlan


@dataclass(frozen=True)
class ModelLayer:
    layer_id: str
    ordinal: int
    parameter_bytes: int

    def __post_init__(self) -> None:
        if not self.layer_id.strip():
            raise ValueError("layer_id is required")
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if self.parameter_bytes < 0:
            raise ValueError("parameter_bytes must be non-negative")


@dataclass(frozen=True)
class ModelPartition:
    partition_id: str
    worker_node_id: str
    layer_ids: tuple[str, ...]
    parameter_bytes: int


@dataclass(frozen=True)
class ModelPartitionPlan:
    execution_plan_id: str
    mode: ExecutionMode
    partitions: tuple[ModelPartition, ...]
    boundary_count: int

    def __post_init__(self) -> None:
        if self.mode not in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            raise ValueError("model partition plan requires pipeline_parallel or p2p_model_partition")
        if not self.partitions:
            raise ValueError("partitions are required")
        if self.boundary_count != max(0, len(self.partitions) - 1):
            raise ValueError("boundary_count must match partition boundaries")


class ModelPartitionPlanner:
    """Assign contiguous ordered layers with deterministic greedy balancing."""

    def plan(self, execution_plan: ExecutionPlan, layers: Sequence[ModelLayer]) -> ModelPartitionPlan:
        if execution_plan.mode not in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            raise ValueError("execution plan mode is not a model partition mode")
        ordered = tuple(sorted(layers, key=lambda layer: (layer.ordinal, layer.layer_id)))
        if not ordered:
            raise ValueError("layers are required")
        if len({layer.layer_id for layer in ordered}) != len(ordered):
            raise ValueError("layer IDs must be unique")
        if tuple(sorted(layer.ordinal for layer in ordered)) != tuple(range(len(ordered))):
            raise ValueError("layer ordinals must be contiguous from zero")
        nodes = tuple(execution_plan.node_ids)
        if len(nodes) > len(ordered):
            raise ValueError("worker count cannot exceed layer count")

        buckets: list[list[ModelLayer]] = [[] for _ in nodes]
        totals = [0 for _ in nodes]
        for layer in ordered:
            index = min(range(len(nodes)), key=lambda i: (totals[i], i))
            buckets[index].append(layer)
            totals[index] += layer.parameter_bytes

        if any(not bucket for bucket in buckets):
            raise ValueError("every partition must contain at least one layer")

        partitions = tuple(
            ModelPartition(
                partition_id=f"{execution_plan.plan_id}:partition:{index}",
                worker_node_id=node,
                layer_ids=tuple(layer.layer_id for layer in bucket),
                parameter_bytes=totals[index],
            )
            for index, (node, bucket) in enumerate(zip(nodes, buckets))
        )
        return ModelPartitionPlan(
            execution_plan_id=execution_plan.plan_id,
            mode=execution_plan.mode,
            partitions=partitions,
            boundary_count=len(partitions) - 1,
        )
