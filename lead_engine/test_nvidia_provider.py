import tempfile
from pathlib import Path

import pytest

from .compute_pool import ComputePool, WorkerIdentity
from .compute_resources import GpuResource, ResourceState
from .nvidia_provider import CommandResult, NvidiaDiscoveryError, NvidiaProvider


QUERY = """index, uuid, name, memory.total [MiB], compute_cap, driver_version, pci.bus_id
0, GPU-aaa, NVIDIA H100, 81920, 9.0, 580.95.05, 00000000:17:00.0
1, GPU-bbb, NVIDIA H100, 81920, 9.0, 580.95.05, 00000000:18:00.0
"""
SMI = """NVIDIA-SMI 580.95.05    Driver Version: 580.95.05    CUDA Version: 13.0
"""
TOPO = """        GPU0    GPU1    CPU Affinity    NUMA
GPU0     X       NV18    0-31            0
GPU1     NV18    X       0-31            0
"""


def fake_runner(args, _timeout):
    args = tuple(args)
    if "--query-gpu=index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id" in args:
        return CommandResult(0, QUERY, "")
    if args[-2:] == ("topo", "-m"):
        return CommandResult(0, TOPO, "")
    return CommandResult(0, SMI, "")


def test_nvidia_discovery_records_stable_gpu_truth_and_topology():
    provider = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=fake_runner, now=lambda: 1234.5)
    snapshot = provider.discover()
    node = snapshot.nodes[0]

    assert snapshot.provider_id == "nvidia"
    assert snapshot.domain_id == "cell-01"
    assert node.gpu_count == 2
    assert [gpu.gpu_uuid for gpu in node.gpus] == ["GPU-aaa", "GPU-bbb"]
    assert node.gpus[0].vram_bytes == 81920 * 1024 * 1024
    assert node.gpus[0].compute_capability == "9.0"
    assert node.gpus[0].driver_version == "580.95.05"
    assert node.gpus[0].cuda_version == "13.0"
    assert node.gpus[0].health_state == ResourceState.HEALTHY
    assert snapshot.evidence["topology_matrix"] == TOPO
    assert snapshot.evidence["driver_supported_cuda_version"] == "13.0"


def test_nvidia_discovery_refuses_missing_uuid():
    def runner(args, timeout):
        if "--query-gpu=index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id" in args:
            return CommandResult(0, QUERY.replace("GPU-aaa", "N/A"), "")
        return CommandResult(0, SMI, "")

    with pytest.raises(NvidiaDiscoveryError, match="UUID"):
        NvidiaProvider(node_id="node-01", runner=runner).discover()


def test_nvidia_discovery_refuses_duplicate_uuid():
    duplicate = QUERY.replace("GPU-bbb", "GPU-aaa")

    def runner(args, timeout):
        if "--query-gpu=index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id" in args:
            return CommandResult(0, duplicate, "")
        return CommandResult(0, SMI, "")

    with pytest.raises(NvidiaDiscoveryError, match="duplicate NVIDIA GPU UUID"):
        NvidiaProvider(node_id="node-01", runner=runner).discover()


def test_nvidia_discovery_does_not_convert_topology_probe_failure_into_false_gpu_failure():
    def runner(args, timeout):
        if args[-2:] == ("topo", "-m"):
            return CommandResult(1, "", "topology unavailable")
        if "--query-gpu=index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id" in args:
            return CommandResult(0, QUERY, "")
        return CommandResult(0, SMI, "")

    snapshot = NvidiaProvider(node_id="node-01", runner=runner).discover()
    assert snapshot.nodes[0].state == ResourceState.AVAILABLE
    assert "topology unavailable" in str(snapshot.evidence["topology_error"])


def test_worker_pool_persists_verified_gpu_inventory():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa", model="NVIDIA H100",
        vram_bytes=81920 * 1024 * 1024, compute_capability="9.0",
        driver_version="580.95.05", cuda_version="13.0", pci_bus_id="00000000:17:00.0",
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    with tempfile.TemporaryDirectory() as directory:
        pool = ComputePool(str(Path(directory) / "workers.sqlite3"))
        identity = WorkerIdentity(
            "node-01", "host", "x86_64", 64, 262144,
            ("lead-processing",), (gpu,), "580.95.05", "13.0", None, (), "healthy", "",
        )
        pool.register(identity)
        worker = pool.worker("node-01")
        assert worker is not None
        assert worker["gpu_resources"][0].gpu_uuid == "GPU-aaa"
        assert worker["gpu_discovery_state"] == "healthy"
