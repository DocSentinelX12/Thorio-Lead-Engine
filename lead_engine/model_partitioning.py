"""Deterministic model partitioning plans for pipeline and P2P execution."""
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
        if self.boundary_count != len(self.partitions) - 1:
            raise ValueError("boundary_count must match partition boundaries")


class ModelPartitionPlanner:
    """Assign contiguous ordered layers using deterministic target-weight cuts."""

    def plan(self, execution_plan: ExecutionPlan, layers: Sequence[ModelLayer]) -> ModelPartitionPlan:
        if execution_plan.mode not in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            raise ValueError("execution plan mode is not a model partition mode")
        ordered = tuple(sorted(layers, key=lambda layer: (layer.ordinal, layer.layer_id)))
        if not ordered:
            raise ValueError("layers are required")
        if len({layer.layer_id for layer in ordered}) != len(ordered):
            raise ValueError("layer IDs must be unique")
        if tuple(layer.ordinal for layer in ordered) != tuple(range(len(ordered))):
            raise ValueError("layer ordinals must be contiguous from zero")
        nodes = tuple(execution_plan.node_ids)
        if len(nodes) > len(ordered):
            raise ValueError("worker count cannot exceed layer count")

        total = sum(layer.parameter_bytes for layer in ordered)
        buckets: list[list[ModelLayer]] = []
        start = 0
        remaining_total = total
        for partition_index in range(len(nodes)):
            remaining_partitions = len(nodes) - partition_index
            remaining_layers = len(ordered) - start
            if remaining_layers < remaining_partitions:
                raise ValueError("cannot give every partition a layer")
            if remaining_partitions == 1:
                bucket = list(ordered[start:])
            else:
                target = remaining_total / remaining_partitions
                end = start + 1
                current = ordered[start].parameter_bytes
                while end < len(ordered) - (remaining_partitions - 1):
                    next_total = current + ordered[end].parameter_bytes
                    if abs(target - next_total) <= abs(target - current):
                        current = next_total
                        end += 1
                    else:
                        break
                bucket = list(ordered[start:end])
            buckets.append(bucket)
            start += len(bucket)
            remaining_total -= sum(layer.parameter_bytes for layer in bucket)

        partitions = tuple(
            ModelPartition(
                partition_id=f"{execution_plan.plan_id}:partition:{index}",
                worker_node_id=node,
                layer_ids=tuple(layer.layer_id for layer in bucket),
                parameter_bytes=sum(layer.parameter_bytes for layer in bucket),
            )
            for index, (node, bucket) in enumerate(zip(nodes, buckets))
        )
        return ModelPartitionPlan(execution_plan.plan_id, execution_plan.mode, partitions, len(partitions) - 1)
