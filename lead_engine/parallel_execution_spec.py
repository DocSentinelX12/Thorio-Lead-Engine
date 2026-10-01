"""Deterministic launch metadata for tightly coupled parallel execution."""
from __future__ import annotations
from dataclasses import dataclass
from .parallel_grouping import ParallelGroupPlan

@dataclass(frozen=True)
class ParallelLaunchSpec:
    execution_plan_id: str
    backend: str
    world_size: int
    ranks: tuple[int, ...]
    node_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]

class ParallelLaunchPlanner:
    def build(self, group: ParallelGroupPlan, *, master_addr: str, master_port: int = 29500) -> ParallelLaunchSpec:
        if group.collective_backend != "nccl":
            raise ValueError("tightly coupled execution requires NCCL")
        master_addr = master_addr.strip()
        if not master_addr:
            raise ValueError("master_addr is required")
        if not 1 <= master_port <= 65535:
            raise ValueError("master_port must be a valid TCP port")
        ranks = tuple(group.ranks)
        env = (
            ("MASTER_ADDR", master_addr),
            ("MASTER_PORT", str(master_port)),
            ("WORLD_SIZE", str(len(ranks))),
        )
        return ParallelLaunchSpec(
            execution_plan_id=group.execution_plan_id,
            backend=group.collective_backend,
            world_size=len(ranks),
            ranks=tuple(rank.rank for rank in ranks),
            node_ids=tuple(rank.node_id for rank in ranks),
            resource_ids=tuple(rank.resource_id for rank in ranks),
            environment=env,
        )

    @staticmethod
    def rank_environment(spec: ParallelLaunchSpec, rank: int) -> tuple[tuple[str, str], ...]:
        if rank not in spec.ranks:
            raise ValueError("rank is not part of the launch spec")
        return spec.environment + (("RANK", str(rank)), ("LOCAL_RANK", "0"))
