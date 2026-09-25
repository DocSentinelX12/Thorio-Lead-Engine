"""Strict validation for durable multi-worker GPU launch contracts."""
from __future__ import annotations

from collections.abc import Mapping, Sequence


class DistributedExecutionContractError(ValueError):
    """Raised when a durable distributed launch plan is internally inconsistent."""


def validate_launch_plan(
    plan: Mapping[str, object], *, expected_endpoint: str | None = None
) -> dict[str, object]:
    """Validate the global distributed process contract before any rank launches."""
    if not isinstance(plan, Mapping):
        raise DistributedExecutionContractError("launch plan must be an object")
    workers = plan.get("workers")
    if not isinstance(workers, Sequence) or isinstance(workers, (str, bytes)) or not workers:
        raise DistributedExecutionContractError("launch plan requires workers")

    try:
        world_size = int(plan.get("world_size", 0))
        nnodes = int(plan.get("nnodes", 0))
    except (TypeError, ValueError) as exc:
        raise DistributedExecutionContractError("world_size and nnodes must be integers") from exc
    if world_size < 2:
        raise DistributedExecutionContractError("world_size must be at least 2")
    if nnodes < 2:
        raise DistributedExecutionContractError("nnodes must be at least 2")

    endpoint = str(plan.get("rendezvous_endpoint") or expected_endpoint or "").strip()
    if not endpoint:
        raise DistributedExecutionContractError("rendezvous_endpoint is required")

    worker_ids: set[str] = set()
    node_ids: set[str] = set()
    global_ranks: set[int] = set()
    total_processes = 0

    for worker in workers:
        if not isinstance(worker, Mapping):
            raise DistributedExecutionContractError("launch plan contains a non-object worker")
        worker_id = str(worker.get("worker_id") or "").strip()
        node_id = str(worker.get("node_id") or "").strip()
        if not worker_id or not node_id:
            raise DistributedExecutionContractError("worker identity is required")
        if worker_id in worker_ids:
            raise DistributedExecutionContractError(f"duplicate worker_id: {worker_id}")
        if node_id in node_ids:
            raise DistributedExecutionContractError(f"duplicate node_id: {node_id}")
        worker_ids.add(worker_id)
        node_ids.add(node_id)

        try:
            process_count = int(worker.get("process_count", 0))
        except (TypeError, ValueError) as exc:
            raise DistributedExecutionContractError(
                f"worker {worker_id} process_count must be an integer"
            ) from exc
        if process_count <= 0:
            raise DistributedExecutionContractError(f"worker {worker_id} has invalid process_count")

        bindings = worker.get("gpu_bindings")
        if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
            raise DistributedExecutionContractError(f"worker {worker_id} is missing gpu_bindings")
        if len(bindings) != process_count:
            raise DistributedExecutionContractError(
                f"worker {worker_id} GPU/process binding count mismatch"
            )

        worker_endpoint = str(worker.get("rendezvous_endpoint") or endpoint).strip()
        if worker_endpoint != endpoint:
            raise DistributedExecutionContractError("rendezvous endpoint mismatch across workers")

        local_ranks: set[int] = set()
        for binding in bindings:
            if not isinstance(binding, Mapping):
                raise DistributedExecutionContractError("GPU binding must be an object")
            try:
                rank = int(binding.get("rank", -1))
                local_rank = int(binding.get("local_rank", -1))
            except (TypeError, ValueError) as exc:
                raise DistributedExecutionContractError("GPU ranks must be integers") from exc
            gpu_uuid = str(binding.get("gpu_uuid") or "").strip()
            gpu_id = str(binding.get("gpu_id") or "").strip()
            if rank < 0 or rank >= world_size or rank in global_ranks:
                raise DistributedExecutionContractError("global rank set is invalid or duplicated")
            if local_rank < 0 or local_rank >= process_count or local_rank in local_ranks:
                raise DistributedExecutionContractError("local rank set is invalid or duplicated")
            if not gpu_uuid or not gpu_id:
                raise DistributedExecutionContractError("GPU binding requires gpu_uuid and gpu_id")
            global_ranks.add(rank)
            local_ranks.add(local_rank)
            total_processes += 1

    if len(node_ids) != nnodes:
        raise DistributedExecutionContractError("nnodes does not match participant nodes")
    if total_processes != world_size:
        raise DistributedExecutionContractError("world_size does not match total process bindings")
    if global_ranks != set(range(world_size)):
        raise DistributedExecutionContractError("global ranks must be contiguous from zero")

    return {
        "verified": True,
        "world_size": world_size,
        "nnodes": nnodes,
        "worker_count": len(worker_ids),
        "binding_count": total_processes,
        "rendezvous_endpoint": endpoint,
    }
