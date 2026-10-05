"""Deterministic groups for tightly coupled distributed execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .execution_fabric_contract import ExecutionCapability, ExecutionMode, ExecutionPlan


_TIGHT_MODES = frozenset({
    ExecutionMode.TENSOR_PARALLEL,
    ExecutionMode.CONTEXT_PARALLEL,
    ExecutionMode.EXPERT_PARALLEL,
    ExecutionMode.SHARDED_STATE,
})


@dataclass(frozen=True)
class ParallelRank:
    rank: int
    node_id: str
    resource_id: str


@dataclass(frozen=True)
class ParallelGroupPlan:
    execution_plan_id: str
    mode: ExecutionMode
    ranks: tuple[ParallelRank, ...]
    collective_backend: str

    def __post_init__(self) -> None:
        if self.mode not in _TIGHT_MODES:
            raise ValueError("parallel group requires a tightly coupled execution mode")
        if not self.ranks:
            raise ValueError("ranks are required")
        if tuple(rank.rank for rank in self.ranks) != tuple(range(len(self.ranks))):
            raise ValueError("ranks must be contiguous from zero")
        if self.collective_backend != "nccl":
            raise ValueError("tightly coupled execution requires NCCL")


class ParallelGroupPlanner:
    def plan(
        self,
        execution_plan: ExecutionPlan,
        capabilities: Sequence[ExecutionCapability],
    ) -> ParallelGroupPlan:
        if execution_plan.mode not in _TIGHT_MODES:
            raise ValueError("execution plan mode is not a tightly coupled mode")
        by_node: dict[str, tuple[str, ExecutionCapability]] = {}
        for capability in capabilities:
            if "nccl" not in {backend.lower() for backend in capability.backends}:
                continue
            for resource_id, node_id in zip(capability.resource_ids, capability.node_ids):
                if node_id in execution_plan.node_ids and node_id not in by_node:
                    by_node[node_id] = (resource_id, capability)
        missing = [node for node in execution_plan.node_ids if node not in by_node]
        if missing:
            raise ValueError(f"missing NCCL-capable nodes: {missing}")

        ranks = tuple(
            ParallelRank(rank=index, node_id=node_id, resource_id=by_node[node_id][0])
            for index, node_id in enumerate(execution_plan.node_ids)
        )
        if len({rank.resource_id for rank in ranks}) != len(ranks):
            raise ValueError("parallel ranks must use distinct resources")
        return ParallelGroupPlan(
            execution_plan_id=execution_plan.plan_id,
            mode=execution_plan.mode,
            ranks=ranks,
            collective_backend="nccl",
        )
