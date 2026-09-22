import pytest
import tempfile
from pathlib import Path

from lead_engine.compute_bridge import REMOTE_SAFE_AGENTS
from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_pool import WorkerIdentity
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
from lead_engine.nccl_all_reduce_probe import build_probe_evidence
from lead_engine.nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


def test_nccl_probe_evidence_builder_contains_only_observed_core_fields():
    evidence = build_probe_evidence(
        rank=1,
        world_size=4,
        nnodes=2,
        expected_sum=10,
        gpu_uuid="GPU-test-1",
        hostname="worker-2",
    )
    assert evidence == {
        "backend": "nccl",
        "rank": 1,
        "world_size": 4,
        "nnodes": 2,
        "local_rank": 0,
        "collective": "all_reduce",
        "expected_sum": 10,
        "verified_on_gpu": True,
        "gpu_uuid": "GPU-test-1",
        "hostname": "worker-2",
    }


def _worker():
    return WorkerIdentity(
        "worker-1",
        "host",
        "x86_64",
        4,
        8192,
        ("lead-processing", "engineering_demand_discovery"),
    )
