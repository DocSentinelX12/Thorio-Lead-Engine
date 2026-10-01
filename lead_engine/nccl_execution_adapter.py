"""NCCL execution adapter contract and physical-proof verifier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .parallel_grouping import ParallelGroupPlan


@dataclass(frozen=True)
class NCCLLaunchSpec:
    world_size: int
    nnodes: int
    master_addr: str
    master_port: int
    socket_ifname: str
    ranks: tuple[int, ...]


@dataclass(frozen=True)
class NCCLPhysicalProof:
    world_size: int
    nnodes: int
    ranks: tuple[int, ...]
    hostnames: tuple[str, ...]
    gpu_uuids: tuple[str, ...]
    collective: str
    expected_sum: int
    proof_ref: str | None


class NCCLExecutionAdapter:
    """Build launch inputs and verify observed NCCL evidence; never fabricates proof."""

    def build_launch_spec(
        self,
        group: ParallelGroupPlan,
        *,
        master_addr: str,
        master_port: int = 29500,
        socket_ifname: str = "",
    ) -> NCCLLaunchSpec:
        if group.collective_backend != "nccl":
            raise ValueError("NCCL adapter requires NCCL collective backend")
        if not master_addr.strip():
            raise ValueError("master_addr is required")
        if not 1 <= master_port <= 65535:
            raise ValueError("master_port must be a valid TCP port")
        if not socket_ifname.strip():
            raise ValueError("socket_ifname is required")
        ranks = tuple(rank.rank for rank in group.ranks)
        return NCCLLaunchSpec(
            world_size=len(ranks),
            nnodes=len(ranks),
            master_addr=master_addr.strip(),
            master_port=master_port,
            socket_ifname=socket_ifname.strip(),
            ranks=ranks,
        )

    def verify_physical_proof(
        self,
        records: Sequence[Mapping[str, object]],
        *,
        proof_ref: str | None = None,
    ) -> NCCLPhysicalProof:
        if not records:
            raise ValueError("NCCL physical proof records are required")
        required = {
            "backend", "rank", "world_size", "nnodes", "collective",
            "expected_sum", "verified_on_gpu", "gpu_uuid", "hostname",
        }
        normalized = [dict(record) for record in records]
        for record in normalized:
            missing = sorted(required - record.keys())
            if missing:
                raise ValueError(f"NCCL proof record missing fields: {missing}")
            if record["backend"] != "nccl" or record["collective"] != "all_reduce":
                raise ValueError("NCCL proof must report the observed NCCL all_reduce")
            if record["verified_on_gpu"] is not True:
                raise ValueError("NCCL proof must contain physical GPU verification")
            if not str(record["gpu_uuid"]).strip() or not str(record["hostname"]).strip():
                raise ValueError("NCCL proof requires observed GPU UUID and hostname")

        world_sizes = {int(record["world_size"]) for record in normalized}
        nnodes = {int(record["nnodes"]) for record in normalized}
        expected = {int(record["expected_sum"]) for record in normalized}
        if len(world_sizes) != 1 or len(nnodes) != 1 or len(expected) != 1:
            raise ValueError("NCCL proof metadata must agree across ranks")
        world_size = next(iter(world_sizes))
        if world_size != len(normalized) or next(iter(nnodes)) != len(normalized):
            raise ValueError("NCCL proof record count must equal world size and node count")

        ranks = tuple(sorted(int(record["rank"]) for record in normalized))
        if ranks != tuple(range(world_size)):
            raise ValueError("NCCL proof ranks must be contiguous from zero")
        hostnames = tuple(str(record["hostname"]) for record in sorted(normalized, key=lambda r: int(r["rank"])))
        gpu_uuids = tuple(str(record["gpu_uuid"]) for record in sorted(normalized, key=lambda r: int(r["rank"])))
        if len(set(hostnames)) != world_size:
            raise ValueError("NCCL proof requires distinct physical hosts")
        if len(set(gpu_uuids)) != world_size:
            raise ValueError("NCCL proof requires distinct physical GPUs")

        return NCCLPhysicalProof(
            world_size=world_size,
            nnodes=next(iter(nnodes)),
            ranks=ranks,
            hostnames=hostnames,
            gpu_uuids=gpu_uuids,
            collective="all_reduce",
            expected_sum=next(iter(expected)),
            proof_ref=proof_ref,
        )
