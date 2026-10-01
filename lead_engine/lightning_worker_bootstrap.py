"""Worker-side bootstrap for a Lightning AI GPU Studio.

The script runs on the acquired machine, not on the acquisition controller.
It uses the existing NVIDIA discovery and physical CUDA execution probe so a
Lightning Studio cannot enter trusted GPU inventory on provider claims alone.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from dataclasses import asdict

from .compute_pool import local_worker_identity


def _ssh_evidence() -> dict[str, object]:
    command = os.environ.get("THORIO_LIGHTNING_SSH_COMMAND", "").strip()
    if not command:
        return {"available": True, "verification": "provider_documented_ssh"}
    try:
        completed = subprocess.run(
            ["sh", "-lc", f"{command} -V"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Lightning SSH verification failed: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Lightning SSH verification command failed: {(completed.stderr or completed.stdout).strip()[-1000:]}")
    return {
        "available": True,
        "verification": "operator_supplied_ssh_command",
        "command_fingerprint": str(hash(command)),
        "version": (completed.stdout or completed.stderr).strip()[-1000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition-id", required=True)
    args = parser.parse_args()
    acquisition_id = str(args.acquisition_id).strip()
    if not acquisition_id:
        raise SystemExit("acquisition-id is required")

    os.environ["THORIO_COMPUTE_ACQUISITION_ID"] = acquisition_id
    identity = local_worker_identity(worker_id=os.environ.get("THORIO_NODE_ID") or socket.gethostname())
    if identity.gpu_discovery_state != "healthy" or not identity.gpu_resources:
        raise SystemExit("Lightning worker did not produce healthy GPU discovery")
    execution = identity.physical_fabric_evidence.get("physical_gpu_execution")
    if not isinstance(execution, list) or len(execution) != len(identity.gpu_resources):
        raise SystemExit("Lightning worker did not produce per-GPU physical CUDA execution evidence")
    evidence = {
        "provider_id": "lightning_ai",
        "acquisition_id": acquisition_id,
        "worker_id": identity.worker_id,
        "hostname": identity.hostname,
        "architecture": identity.architecture,
        "cpu_count": identity.cpu_count,
        "memory_mb": identity.memory_mb,
        "gpu_discovery_state": identity.gpu_discovery_state,
        "gpu_resources": [asdict(gpu) for gpu in identity.gpu_resources],
        "driver_version": identity.driver_version,
        "cuda_version": identity.cuda_version,
        "nccl_version": identity.nccl_version,
        "nic_names": list(identity.nic_names),
        "domain_id": identity.domain_id,
        "physical_fabric_evidence": dict(identity.physical_fabric_evidence),
        "physical_gpu_execution": execution,
        "ssh": _ssh_evidence(),
        "enrollment_contract": "/workers/register",
    }
    print("THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps(evidence, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
