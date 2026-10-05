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
import sys
import urllib.error
import urllib.request
from dataclasses import asdict

from .compute_pool import local_worker_identity



def _enroll_with_coordinator(evidence: dict[str, object]) -> dict[str, object]:
    coordinator_url = os.environ.get("THORIO_COMPUTE_COORDINATOR_URL", "").strip().rstrip("/")
    auth_token = os.environ.get("THORIO_COMPUTE_AUTH_TOKEN", "").strip()
    if bool(coordinator_url) != bool(auth_token):
        raise RuntimeError(
            "THORIO_COMPUTE_COORDINATOR_URL and THORIO_COMPUTE_AUTH_TOKEN must be provided together"
        )
    if not coordinator_url:
        required = os.environ.get("THORIO_LIGHTNING_REQUIRE_COORDINATOR_ENROLLMENT", "0").strip().lower() in {"1", "true", "yes", "on"}
        if required:
            raise RuntimeError(
                "Thorio coordinator enrollment is required for Lightning acquisition but is not configured"
            )
        return {"attempted": False, "status": "not_configured"}

    payload = json.dumps(evidence, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        f"{coordinator_url}/workers/register",
        data=payload,
        headers={
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            status = int(response.status)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Thorio worker enrollment failed: {exc}") from exc

    if status != 200:
        raise RuntimeError(f"Thorio worker enrollment returned HTTP {status}")
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Thorio worker enrollment returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Thorio worker enrollment returned a non-object response")
    return {
        "attempted": True,
        "status": "registered",
        "response": result,
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
        "enrollment_contract": "/workers/register",
    }
    enrollment = _enroll_with_coordinator(evidence)
    evidence["coordinator_enrollment"] = enrollment
    if enrollment["attempted"] and enrollment["status"] != "registered":
        raise SystemExit("Lightning worker did not complete authenticated Thorio enrollment")
    print("THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps(evidence, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
