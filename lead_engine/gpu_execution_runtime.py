"""Production GPU workload execution boundary.

The runner executes an explicitly authorized workload command on the exact
physical GPU resources already allocated by ComputeCoordinator. It never
chooses resources and never creates a second queue or scheduler.

All accelerator identity claims are revalidated locally with nvidia-smi before
launch. The command receives only the allocated CUDA devices. Completion
evidence includes process outcome and immutable SHA-256 references for declared
output/checkpoint files when those files exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class GpuExecutionError(RuntimeError):
    """Raised when an allocated GPU workload cannot be proven to have executed."""


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _artifact_ref(path: str, *, attempt_id: str, generation: int, kind: str) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise GpuExecutionError(f"declared {kind} file does not exist: {candidate}")
    digest, size = _sha256_file(candidate)
    return {
        "kind": kind,
        "path": str(candidate),
        "sha256": digest,
        "size_bytes": size,
        "attempt_id": attempt_id,
        "generation": generation,
        "immutable": True,
    }


def _allocated_gpu_bindings(allocation: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = allocation.get("capability_evidence")
    if not isinstance(evidence, (list, tuple)):
        raise GpuExecutionError("physical allocation has no capability evidence")
    bindings = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        resource_id = str(item.get("resource_id") or "").strip()
        gpu_id = str(item.get("gpu_id") or "").strip()
        gpu_uuid = str(item.get("gpu_uuid") or "").strip()
        if not resource_id or not gpu_id or not gpu_uuid:
            continue
        if "/cpu" in resource_id:
            continue
        bindings.append({"resource_id": resource_id, "gpu_id": gpu_id, "gpu_uuid": gpu_uuid})
    if not bindings:
        raise GpuExecutionError("physical allocation contains no concrete GPU identity")
    unique_ids = {item["resource_id"] for item in bindings}
    unique_uuids = {item["gpu_uuid"] for item in bindings}
    if len(unique_ids) != len(bindings) or len(unique_uuids) != len(bindings):
        raise GpuExecutionError("physical allocation contains duplicate GPU identities")
    return bindings


def verify_allocated_nvidia_gpus(
    bindings: Sequence[Mapping[str, Any]],
    *,
    runner: Callable[[Sequence[str]], tuple[int, str, str]],
) -> dict[str, Any]:
    if not bindings:
        raise GpuExecutionError("at least one GPU binding is required")
    rc, stdout, stderr = runner(
        ("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits")
    )
    if rc != 0:
        raise GpuExecutionError(f"nvidia-smi identity verification failed: {(stderr or stdout).strip()[:1000]}")
    observed: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = [part.strip() for part in line.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            observed[parts[0]] = parts[1]
    normalized = []
    for binding in bindings:
        gpu_id = str(binding["gpu_id"]).removeprefix("gpu-")
        expected_uuid = str(binding["gpu_uuid"])
        if not gpu_id.isdigit() or observed.get(gpu_id) != expected_uuid:
            raise GpuExecutionError(
                f"allocated GPU identity mismatch for {binding['resource_id']}: "
                f"expected {expected_uuid}, observed {observed.get(gpu_id, '<missing>')}"
            )
        normalized.append({"resource_id": binding["resource_id"], "gpu_id": gpu_id, "gpu_uuid": expected_uuid})
    return {"verified": True, "gpu_bindings": normalized}


def execute_gpu_workload(
    client: Any,
    task: Mapping[str, Any],
    *,
    heartbeat_seconds: float = 15.0,
    runner: Callable[..., tuple[int, str, str]] | None = None,
) -> dict[str, Any]:
    """Execute one coordinator-leased GPU workload and return verified evidence."""
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    task_id = str(task.get("task_id") or "").strip()
    attempt_id = str(task.get("attempt_id") or "").strip()
    lease_token = str(task.get("lease_token") or "").strip()
    try:
        generation = int(task.get("generation"))
    except (TypeError, ValueError):
        generation = 0
    allocation = task.get("physical_allocation")
    payload = task.get("payload")
    if not task_id or not attempt_id or not lease_token or generation < 1:
        raise GpuExecutionError("complete execution identity is required")
    if not isinstance(allocation, Mapping):
        raise GpuExecutionError("GPU workload requires a physical allocation")
    if not isinstance(payload, Mapping):
        raise GpuExecutionError("GPU workload payload must be an object")
    command = payload.get("command")
    if not isinstance(command, (list, tuple)) or not command or any(not str(item).strip() for item in command):
        raise GpuExecutionError("GPU workload command must be a non-empty argument list")
    command = tuple(str(item) for item in command)
    bindings = _allocated_gpu_bindings(allocation)

    def run_command(args: Sequence[str], env: Mapping[str, str] | None = None, timeout: float | None = None):
        if runner is not None:
            return runner(args, env, timeout)
        try:
            completed = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                env=None if env is None else dict(env),
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GpuExecutionError(f"GPU workload process failed to start or timed out: {exc}") from exc
        return completed.returncode, completed.stdout, completed.stderr

    identity = verify_allocated_nvidia_gpus(
        bindings,
        runner=lambda args: run_command(args, None, 15.0),
    )
    client.fabric_state(attempt_id, generation, lease_token, "launching")
    stop = threading.Event()
    heartbeat_error: list[str] = []

    def heartbeat() -> None:
        while not stop.wait(heartbeat_seconds):
            try:
                response = client.fabric_heartbeat(attempt_id, generation, lease_token)
                if response.get("ok") is not True:
                    heartbeat_error.append("coordinator rejected GPU workload heartbeat")
                    stop.set()
                    return
            except Exception as exc:
                heartbeat_error.append(str(exc))
                stop.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    started_at = time.time()
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ",".join(item["gpu_id"] for item in identity["gpu_bindings"])
    env["THORIO_FABRIC_ATTEMPT_ID"] = attempt_id
    env["THORIO_FABRIC_GENERATION"] = str(generation)
    env["THORIO_EXPECTED_GPU_UUIDS"] = json.dumps([item["gpu_uuid"] for item in identity["gpu_bindings"]])
    client.fabric_state(attempt_id, generation, lease_token, "active")
    try:
        timeout = payload.get("timeout_seconds")
        timeout_seconds = float(timeout) if timeout is not None else None
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        rc, stdout, stderr = run_command(command, env, timeout_seconds)
        if heartbeat_error:
            raise GpuExecutionError(heartbeat_error[-1])
        if int(rc) != 0:
            raise GpuExecutionError(f"GPU workload exited with code {rc}: {str(stderr)[-4000:]}")
        artifacts: list[dict[str, Any]] = []
        for path in payload.get("output_artifacts") or ():
            artifacts.append(_artifact_ref(str(path), attempt_id=attempt_id, generation=generation, kind="output"))
        checkpoint = payload.get("checkpoint_path")
        if checkpoint:
            artifacts.append(_artifact_ref(str(checkpoint), attempt_id=attempt_id, generation=generation, kind="checkpoint"))
        finished_at = time.time()
        evidence = {
            "verified": True,
            "execution_kind": "gpu_workload",
            "attempt_id": attempt_id,
            "generation": generation,
            "task_id": task_id,
            "worker_id": client.worker_id,
            "gpu_bindings": identity["gpu_bindings"],
            "cuda_visible_devices": env["CUDA_VISIBLE_DEVICES"],
            "command": list(command),
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": finished_at - started_at,
            "return_code": int(rc),
            "stdout": str(stdout)[-8000:],
            "stderr": str(stderr)[-8000:],
            "artifact_refs": artifacts,
        }
        if not client.fabric_record_verification(attempt_id, generation, lease_token, evidence).get("ok", True):
            raise GpuExecutionError("coordinator rejected GPU execution evidence")
        converged = client.fabric_converge(attempt_id, generation, lease_token)
        if not converged.get("converged", True):
            raise GpuExecutionError("GPU execution did not converge in the coordinator")
        return evidence
    except Exception as exc:
        try:
            client.fabric_state(attempt_id, generation, lease_token, "failed", str(exc))
        finally:
            stop.set()
            thread.join(timeout=max(1.0, heartbeat_seconds))
        raise
    finally:
        stop.set()
        thread.join(timeout=max(1.0, heartbeat_seconds))
