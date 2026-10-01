"""Real two-node NCCL proof executed inside a Modal Cluster.

The cluster is provisioned by Modal itself. Each clustered container executes
one Thorio NCCL rank on one physical GPU allocation. No simulated or local
fallback is permitted.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import modal

app = modal.App("thorio-physical-modal-nccl-proof")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install("torch")
    .add_local_python_source("lead_engine")
)

GPU_TYPE = os.environ.get("THORIO_MODAL_GPU", "T4")
WORLD_SIZE = 2
NNODES = 2
MASTER_PORT = 29500


def _run_rank() -> dict[str, object]:
    cluster = modal.Cluster.from_context()
    rank = cluster.container_rank()
    container_ids = list(cluster.container_ids())
    container_ips = list(cluster.container_ips(family="ipv4"))
    if len(container_ids) != WORLD_SIZE or len(container_ips) != WORLD_SIZE:
        raise RuntimeError(
            f"Modal cluster membership mismatch: containers={len(container_ids)} ips={len(container_ips)}"
        )

    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,name", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    if len(gpu) != 1:
        raise RuntimeError(f"Expected exactly one GPU in each Modal proof container, got {gpu!r}")
    gpu_uuid, gpu_name = [part.strip() for part in gpu[0].split(",", 1)]
    if not gpu_uuid:
        raise RuntimeError("Modal proof container did not expose a physical GPU UUID")

    env = os.environ.copy()
    env.update(
        {
            "RANK": str(rank),
            "WORLD_SIZE": str(WORLD_SIZE),
            "LOCAL_RANK": "0",
            "THORIO_EXPECTED_RANK": str(rank),
            "THORIO_EXPECTED_WORLD_SIZE": str(WORLD_SIZE),
            "THORIO_EXPECTED_NNODES": str(NNODES),
            "MASTER_ADDR": container_ips[0],
            "MASTER_PORT": str(MASTER_PORT),
            "NCCL_DEBUG": "INFO",
            "NCCL_DEBUG_SUBSYS": "NET",
        }
    )
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "lead_engine.nccl_all_reduce_probe"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    elapsed = time.monotonic() - started
    log = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Thorio NCCL rank {rank} failed after {elapsed:.2f}s:\n{log[-12000:]}"
        )

    marker = "THORIO_NCCL_PROBE_OK "
    matches = [
        json.loads(line[len(marker) :])
        for line in log.splitlines()
        if line.startswith(marker)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one NCCL probe marker for rank {rank}, got {len(matches)}")

    from lead_engine.nvidia_runtime import NvidiaRuntime

    probe = matches[0]
    network = NvidiaRuntime.parse_nccl_network_evidence(log)
    if probe.get("backend") != "nccl" or probe.get("collective") != "all_reduce":
        raise RuntimeError(f"Rank {rank} did not prove NCCL all_reduce")
    if probe.get("verified_on_gpu") is not True:
        raise RuntimeError(f"Rank {rank} did not prove physical GPU execution")
    if int(probe.get("world_size", -1)) != WORLD_SIZE:
        raise RuntimeError(f"Rank {rank} reported the wrong world size")
    if int(probe.get("nnodes", -1)) != NNODES:
        raise RuntimeError(f"Rank {rank} reported the wrong node count")
    if int(probe.get("expected_sum", -1)) != 3:
        raise RuntimeError(f"Rank {rank} produced the wrong all_reduce result")
    if not network.get("network_transport"):
        raise RuntimeError(f"Rank {rank} produced no NCCL network transport evidence")
    if not network.get("peer_connections"):
        raise RuntimeError(f"Rank {rank} produced no NCCL peer-connection evidence")
    if "NCCL INFO" not in log:
        raise RuntimeError(f"Rank {rank} produced no NCCL INFO evidence")

    return {
        "verified": True,
        "rank": rank,
        "world_size": WORLD_SIZE,
        "nnodes": NNODES,
        "gpu_uuid": gpu_uuid,
        "gpu_name": gpu_name,
        "hostname": socket.gethostname(),
        "modal_cluster_id": cluster.object_id,
        "modal_cluster_size": WORLD_SIZE,
        "modal_container_id": container_ids[rank],
        "modal_container_ids": container_ids,
        "modal_container_ips": container_ips,
        "collective": "all_reduce",
        "expected_sum": 3,
        "network_transport": network["network_transport"],
        "hca_selections": list(network.get("hca_selections") or ()),
        "peer_connections": list(network.get("peer_connections") or ()),
        "network_evidence_lines": list(network.get("network_evidence_lines") or ()),
        "gpu_direct_rdma": bool(network.get("gpu_direct_rdma")),
        "probe_elapsed_seconds": elapsed,
        "nccl_log": log,
    }


@app.function(
    image=image,
    gpu=GPU_TYPE,
    timeout=240,
)
@modal.clustered(size=WORLD_SIZE, rdma=False)
def physical_nccl_probe(proof_sha: str) -> dict[str, object]:
    record = _run_rank()
    record["proof_sha"] = proof_sha
    return record


@app.local_entrypoint()
def main(proof_sha: str = "") -> None:
    if not proof_sha.strip():
        raise SystemExit("proof_sha is required")
    records = list(physical_nccl_probe.remote(proof_sha))
    if len(records) != WORLD_SIZE:
        raise SystemExit(f"Expected {WORLD_SIZE} Modal rank results, received {len(records)}")

    # Modal clustered functions return rank 0 output only, so this entrypoint
    # intentionally validates the returned rank plus the cluster-level facts
    # emitted by the provider. The workflow obtains rank 1 from Modal logs.
    record = records[0] if isinstance(records[0], dict) else {}
    print("THORIO_MODAL_NCCL_RANK0 " + json.dumps(record, sort_keys=True))
