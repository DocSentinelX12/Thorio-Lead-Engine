"""NCCL execution planning and physical-proof boundary.

NCCL is intentionally isolated from the other execution families. This module
plans a real collective launch and states exactly what must be proven by the
runtime. It never fabricates physical execution evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from .execution_fabric_contract import ExecutionMode, ExecutionPlan


@dataclass(frozen=True)
class NCCLLaunchSpec:
    master_addr: str
    master_port: int
    socket_interface: str
    collective: str = "all_reduce"

    def __post_init__(self) -> None:
        if not self.master_addr.strip():
            raise ValueError("master address is required")
        if not 1 <= self.master_port <= 65535:
            raise ValueError("master port must be between 1 and 65535")
        if not self.socket_interface.strip():
            raise ValueError("socket interface is required")
        if self.collective not in {"all_reduce", "all_gather", "reduce_scatter", "broadcast", "barrier"}:
            raise ValueError("unsupported NCCL collective")


@dataclass(frozen=True)
class NCCLExecutionPlan:
    execution_plan_id: str
    world_size: int
    nnodes: int
    rank_assignments: tuple[tuple[str, str, str], ...]
    master_addr: str
    master_port: int
    socket_interface: str
    collective: str
    evidence_state: str = "plan_only"
    physical_execution_verified: bool = False

    @property
    def required_physical_proof(self) -> tuple[str, ...]:
        return (
            "cuda_available",
            "nccl_backend_available",
            "gpu_uuid_observed",
            "gpu_uuid_matches_allocation",
            "distinct_physical_hosts",
            "collective_result_verified",
            "nccl_runtime_evidence",
        )


class NCCLExecutionPlanner:
    """Create a strict multi-node NCCL launch plan only."""

    def plan(self, execution_plan: ExecutionPlan, launch: NCCLLaunchSpec) -> NCCLExecutionPlan:
        if execution_plan.mode is not ExecutionMode.NCCL:
            raise ValueError("execution plan mode must be nccl")
        if execution_plan.execution_started or execution_plan.physical_execution_verified:
            raise ValueError("NCCL planner accepts plan-only execution plans")
        if execution_plan.worker_count < 2:
            raise ValueError("NCCL requires at least two workers")
        if len(execution_plan.resource_ids) != execution_plan.worker_count:
            raise ValueError("NCCL requires one GPU resource per worker")
        if len(set(execution_plan.node_ids)) != execution_plan.worker_count:
            raise ValueError("NCCL requires distinct physical node identities")
        assignments = tuple(
            (str(rank), node_id, resource_id)
            for rank, (node_id, resource_id)
            in enumerate(zip(execution_plan.node_ids, execution_plan.resource_ids))
        )
        return NCCLExecutionPlan(
            execution_plan_id=execution_plan.plan_id,
            world_size=execution_plan.worker_count,
            nnodes=execution_plan.worker_count,
            rank_assignments=assignments,
            master_addr=launch.master_addr.strip(),
            master_port=launch.master_port,
            socket_interface=launch.socket_interface.strip(),
            collective=launch.collective,
        )
