"""Capability-aware composition of execution families into one hybrid plan."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .execution_fabric_contract import ExecutionCapability, ExecutionMode, ExecutionPlan

_DISTRIBUTED = frozenset({
    ExecutionMode.DATA_PARALLEL, ExecutionMode.PIPELINE_PARALLEL,
    ExecutionMode.TENSOR_PARALLEL, ExecutionMode.CONTEXT_PARALLEL,
    ExecutionMode.EXPERT_PARALLEL, ExecutionMode.SHARDED_STATE,
    ExecutionMode.P2P_MODEL_PARTITION, ExecutionMode.NCCL,
})
_TIGHT = frozenset({
    ExecutionMode.TENSOR_PARALLEL, ExecutionMode.CONTEXT_PARALLEL,
    ExecutionMode.EXPERT_PARALLEL, ExecutionMode.SHARDED_STATE,
})

@dataclass(frozen=True)
class HybridExecutionPlan:
    execution_plan_id: str
    stages: tuple[ExecutionMode, ...]
    node_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError("hybrid stages are required")
        if ExecutionMode.HYBRID in self.stages:
            raise ValueError("hybrid cannot contain itself")
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("hybrid stages must be unique")

class HybridExecutionPlanner:
    def plan(self, base_plan: ExecutionPlan, stages: Sequence[ExecutionMode],
             capabilities: Sequence[ExecutionCapability]) -> HybridExecutionPlan:
        if base_plan.mode is not ExecutionMode.HYBRID:
            raise ValueError("base execution plan must use hybrid mode")
        ordered = tuple(stages)
        if not ordered:
            raise ValueError("at least one hybrid stage is required")
        if any(not isinstance(stage, ExecutionMode) for stage in ordered):
            raise ValueError("hybrid stages must be ExecutionMode values")
        selected = []
        for node_id in base_plan.node_ids:
            matches = [c for c in capabilities if node_id in c.node_ids]
            if len(matches) != 1:
                raise ValueError(f"expected exactly one capability for node {node_id}")
            selected.append(matches[0])
        for stage in ordered:
            if stage is ExecutionMode.HYBRID:
                raise ValueError("hybrid cannot contain itself")
            if stage in _DISTRIBUTED and len(base_plan.node_ids) < 2:
                raise ValueError("distributed hybrid stages require multiple nodes")
            if any(stage not in c.supported_modes for c in selected):
                raise ValueError(f"hybrid stage {stage.value} is unsupported by a selected node")
            if stage in _TIGHT and any("nccl" not in {b.lower() for b in c.backends} for c in selected):
                raise ValueError("tightly coupled hybrid stages require NCCL on every selected node")
        return HybridExecutionPlan(base_plan.plan_id, ordered, base_plan.node_ids, base_plan.resource_ids)
