"""Real NCCL all-reduce verification process.

Each invocation is exactly one distributed rank. The coordinator launches one
process per allocated GPU so heterogeneous GPU counts per node are supported
without relying on torchrun's homogeneous local-worker contract.
"""
from __future__ import annotations

import json
import os
import socket


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
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    expected_world_size = int(os.environ.get("THORIO_EXPECTED_WORLD_SIZE", str(world_size)))
    expected_rank = int(os.environ.get("THORIO_EXPECTED_RANK", str(rank)))
    expected_gpu_uuid = str(os.environ.get("THORIO_EXPECTED_GPU_UUID") or "").strip()

    if world_size != expected_world_size:
        raise SystemExit(f"WORLD_SIZE mismatch: expected {expected_world_size}, got {world_size}")
    if rank != expected_rank:
        raise SystemExit(f"RANK mismatch: expected {expected_rank}, got {rank}")
    if local_rank != 0:
        raise SystemExit(f"single-GPU launch requires LOCAL_RANK=0, got {local_rank}")

    torch.cuda.set_device(0)
    device = torch.device("cuda", 0)
    properties = torch.cuda.get_device_properties(device)
    observed_gpu_uuid = str(getattr(properties, "uuid", "") or "").strip()
    if not observed_gpu_uuid:
        raise SystemExit("CUDA runtime did not expose the bound GPU UUID")
    if expected_gpu_uuid and observed_gpu_uuid != expected_gpu_uuid:
        raise SystemExit(
            f"GPU UUID mismatch: expected {expected_gpu_uuid}, observed {observed_gpu_uuid}"
        )

    dist.init_process_group(backend="nccl", rank=rank, world_size=world_size)
    try:
        value = torch.tensor([rank + 1], dtype=torch.int64, device=device)
        dist.all_reduce(value, op=dist.ReduceOp.SUM)
        expected = world_size * (world_size + 1) // 2
        actual = int(value.item())
        if actual != expected:
            raise SystemExit(f"NCCL all-reduce mismatch: expected {expected}, got {actual}")
        dist.barrier()
        print("THORIO_NCCL_PROBE_OK " + json.dumps({
            "backend": "nccl",
            "rank": rank,
            "world_size": world_size,
            "local_rank": 0,
            "collective": "all_reduce",
            "expected_sum": expected,
            "verified_on_gpu": True,
            "gpu_uuid": observed_gpu_uuid,
            "hostname": socket.gethostname(),
        }, sort_keys=True), flush=True)
    finally:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
