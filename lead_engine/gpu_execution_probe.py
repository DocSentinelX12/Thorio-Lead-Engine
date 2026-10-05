"""Single-GPU CUDA execution proof used by remote physical GPU workers.

This probe performs an actual CUDA tensor operation on the allocated device and
emits evidence only after CUDA synchronization succeeds.
"""
from __future__ import annotations

import argparse
import json
import os
import time


def normalize_gpu_uuid(value: object) -> str:
    """Canonicalize NVIDIA GPU UUID formatting without changing device identity."""
    normalized = str(value or "").strip()
    if normalized.upper().startswith("GPU-"):
        normalized = normalized[4:]
    return f"GPU-{normalized}" if normalized else ""


def run_probe(expected_gpu_uuid: str) -> dict[str, object]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(f"PyTorch with CUDA support is required: {exc}") from exc

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to claim physical GPU execution")

    torch.cuda.set_device(0)
    device = torch.device("cuda", 0)
    properties = torch.cuda.get_device_properties(device)
    observed_gpu_uuid = normalize_gpu_uuid(getattr(properties, "uuid", ""))
    expected_gpu_uuid = normalize_gpu_uuid(expected_gpu_uuid)
    if not observed_gpu_uuid:
        raise RuntimeError("CUDA runtime did not expose the physical GPU UUID")
    if expected_gpu_uuid and observed_gpu_uuid != expected_gpu_uuid:
        raise RuntimeError(
            f"GPU UUID mismatch: expected {expected_gpu_uuid}, observed {observed_gpu_uuid}"
        )

    left = torch.arange(16, dtype=torch.float32, device=device).reshape(4, 4)
    right = torch.eye(4, dtype=torch.float32, device=device)
    started = time.perf_counter()
    result = torch.matmul(left, right)
    checksum = float(result.sum().item())
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if checksum != 120.0:
        raise RuntimeError(f"CUDA execution checksum mismatch: expected 120.0, got {checksum}")

    evidence = {
        "verified": True,
        "execution_backend": "cuda",
        "operation": "torch_cuda_matmul",
        "gpu_uuid": observed_gpu_uuid,
        "gpu_name": str(properties.name),
        "cuda_device_index": 0,
        "checksum": checksum,
        "elapsed_ms": elapsed_ms,
    }
    proof_sha = os.environ.get("THORIO_PROOF_SHA", "").strip()
    if proof_sha:
        evidence["proof_sha"] = proof_sha
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-gpu-uuid", default="")
    args = parser.parse_args()
    evidence = run_probe(str(args.expected_gpu_uuid).strip())
    print("THORIO_GPU_EXECUTION_PROBE_OK " + json.dumps(evidence, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
