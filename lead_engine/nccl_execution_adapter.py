"""NCCL launch, observation parsing, and physical-proof verification."""
from __future__ import annotations
from dataclasses import dataclass
import json
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
class NCCLCommand:
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]

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
    """Build execution inputs and verify only observed NCCL evidence."""

    def build_launch_spec(self, group: ParallelGroupPlan, *, master_addr: str, master_port: int = 29500, socket_ifname: str = "") -> NCCLLaunchSpec:
        if group.collective_backend != "nccl":
            raise ValueError("NCCL adapter requires NCCL collective backend")
        if not master_addr.strip():
            raise ValueError("master_addr is required")
        if not 1 <= master_port <= 65535:
            raise ValueError("master_port must be a valid TCP port")
        if not socket_ifname.strip():
            raise ValueError("socket_ifname is required")
        ranks = tuple(rank.rank for rank in group.ranks)
        return NCCLLaunchSpec(len(ranks), len(ranks), master_addr.strip(), master_port, socket_ifname.strip(), ranks)

    def build_command(self, spec: NCCLLaunchSpec, *, executable: str, arguments: Sequence[str] = ()) -> NCCLCommand:
        executable = executable.strip()
        if not executable:
            raise ValueError("executable is required")
        args = tuple(str(arg) for arg in arguments)
        env = (
            ("MASTER_ADDR", spec.master_addr),
            ("MASTER_PORT", str(spec.master_port)),
            ("WORLD_SIZE", str(spec.world_size)),
            ("NCCL_SOCKET_IFNAME", spec.socket_ifname),
        )
        return NCCLCommand((executable, *args), env)

    @staticmethod
    def parse_observed_records(raw_output: str) -> tuple[Mapping[str, object], ...]:
        """Accept only newline-delimited JSON records emitted by the worker."""
        records = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("evidence_type") == "nccl_physical_execution":
                records.append(record)
        if not records:
            raise ValueError("no observed NCCL physical execution records were found")
        return tuple(records)

    def verify_physical_proof(self, records: Sequence[Mapping[str, object]], *, proof_ref: str | None = None) -> NCCLPhysicalProof:
        if not records:
            raise ValueError("NCCL physical proof records are required")
        required = {"backend", "rank", "world_size", "nnodes", "collective", "expected_sum", "verified_on_gpu", "gpu_uuid", "hostname"}
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
        world_sizes = {int(r["world_size"]) for r in normalized}
        nnodes = {int(r["nnodes"]) for r in normalized}
        expected = {int(r["expected_sum"]) for r in normalized}
        if len(world_sizes) != 1 or len(nnodes) != 1 or len(expected) != 1:
            raise ValueError("NCCL proof metadata must agree across ranks")
        world_size = next(iter(world_sizes))
        if world_size != len(normalized) or next(iter(nnodes)) != len(normalized):
            raise ValueError("NCCL proof record count must equal world size and node count")
        ordered = sorted(normalized, key=lambda r: int(r["rank"]))
        ranks = tuple(int(r["rank"]) for r in ordered)
        if ranks != tuple(range(world_size)):
            raise ValueError("NCCL proof ranks must be contiguous from zero")
        hostnames = tuple(str(r["hostname"]) for r in ordered)
        gpu_uuids = tuple(str(r["gpu_uuid"]) for r in ordered)
        if len(set(hostnames)) != world_size:
            raise ValueError("NCCL proof requires distinct physical hosts")
        if len(set(gpu_uuids)) != world_size:
            raise ValueError("NCCL proof requires distinct physical GPUs")
        return NCCLPhysicalProof(world_size, next(iter(nnodes)), ranks, hostnames, gpu_uuids, "all_reduce", next(iter(expected)), proof_ref)
