"""Execution-ready contracts for model-partitioned GPU workloads.

This module plans transport and stage metadata only. It never claims that a
partition executed until an adapter supplies observed evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .execution_fabric_contract import ExecutionMode, ExecutionPlan
from .model_partitioning import ModelPartitionPlan

@dataclass(frozen=True)
class PartitionBoundary:
    upstream_partition_id: str
    downstream_partition_id: str
    transport: str
    ordinal: int

@dataclass(frozen=True)
class PartitionExecutionSpec:
    execution_plan_id: str
    mode: ExecutionMode
    partitions: tuple[str, ...]
    boundaries: tuple[PartitionBoundary, ...]
    world_size: int
    requires_p2p_transport: bool

class ModelPartitionExecutionPlanner:
    def build(self, execution_plan: ExecutionPlan, partition_plan: ModelPartitionPlan, *, transport: str = "p2p") -> PartitionExecutionSpec:
        if execution_plan.mode not in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            raise ValueError("execution plan is not a model-partition execution mode")
        if partition_plan.execution_plan_id != execution_plan.plan_id:
            raise ValueError("partition plan does not belong to execution plan")
        if partition_plan.mode != execution_plan.mode:
            raise ValueError("partition mode does not match execution mode")
        transport = transport.strip().lower()
        if transport not in {"p2p", "cuda_ipc", "rdma"}:
            raise ValueError("unsupported partition transport")
        partitions = partition_plan.partitions
        boundaries = tuple(
            PartitionBoundary(partitions[i].partition_id, partitions[i + 1].partition_id, transport, i)
            for i in range(len(partitions) - 1)
        )
        return PartitionExecutionSpec(
            execution_plan_id=execution_plan.plan_id,
            mode=execution_plan.mode,
            partitions=tuple(partition.partition_id for partition in partitions),
            boundaries=boundaries,
            world_size=len(partitions),
            requires_p2p_transport=True,
        )

    @staticmethod
    def validate_observed_partition_order(spec: PartitionExecutionSpec, observed_partition_ids: Sequence[str]) -> None:
        if tuple(str(item) for item in observed_partition_ids) != spec.partitions:
            raise ValueError("observed partition order does not match the planned partition order")
