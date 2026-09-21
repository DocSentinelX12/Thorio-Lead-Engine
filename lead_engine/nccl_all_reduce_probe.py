"""Real NCCL all-reduce verification process launched by torchrun.

This module is intentionally tiny and fail-closed. It requires PyTorch with
CUDA and NCCL support, initializes an NCCL process group, performs an actual
GPU all-reduce, validates the result against WORLD_SIZE, and emits a durable
success marker only after the collective completes.
"""
from __future__ import annotations

import json
import os


def main() -> None:
    try:
        import torch
        import torch.distributed as dist
    except ImportError as exc:
        raise SystemExit(f"PyTorch with torch.distributed is required: {exc}")

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable; refusing to claim NCCL capability")
    if not dist.is_nccl_available():
        raise SystemExit("NCCL backend is unavailable; refusing to claim distributed capability")

    rank = int(os.environ["RANK"])
    world_size = int(os.environ["WORLD_SIZE"])
    local_rank = int(os.environ["LOCAL_RANK"])
    expected_world_size = int(os.environ.get("THORIO_EXPECTED_WORLD_SIZE", str(world_size)))
    if world_size != expected_world_size:
        raise SystemExit(f"WORLD_SIZE mismatch: expected {expected_world_size}, got {world_size}")

    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)
    dist.init_process_group(backend="nccl", rank=rank, world_size=world_size)
    try:
        value = torch.tensor([rank + 1], dtype=torch.int64, device=device)
        dist.all_reduce(value, op=dist.ReduceOp.SUM)
        expected = world_size * (world_size + 1) // 2
        actual = int(value.item())
        if actual != expected:
            raise SystemExit(f"NCCL all-reduce mismatch: expected {expected}, got {actual}")
        dist.barrier()
        if rank == 0:
            print("THORIO_NCCL_PROBE_OK " + json.dumps({
                "backend": "nccl",
                "world_size": world_size,
                "collective": "all_reduce",
                "expected_sum": expected,
                "verified_on_gpu": True,
            }, sort_keys=True), flush=True)
    finally:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
