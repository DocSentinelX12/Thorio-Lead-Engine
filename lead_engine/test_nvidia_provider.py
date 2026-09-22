import tempfile
from pathlib import Path

import pytest

from .compute_pool import ComputePool, WorkerIdentity
from .compute_resources import GpuResource, ResourceState
from .nvidia_provider import CommandResult, NvidiaDiscoveryError, NvidiaProvider
from .nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


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
    assert node.gpus[0].cuda_version is None
    assert node.gpus[0].health_state == ResourceState.HEALTHY
    assert snapshot.evidence["topology_matrix"] == TOPO
    assert snapshot.evidence["driver_supported_cuda_version"] == "13.0"
    assert snapshot.evidence["cuda_toolkit_version"] is None


def test_nvidia_discovery_records_verified_network_topology_evidence():
    network_addresses = """[
      {
        "ifname": "eth0",
        "operstate": "UP",
        "mtu": 9000,
        "address": "aa:bb:cc:dd:ee:ff",
        "addr_info": [
          {"family": "inet", "local": "10.10.20.15", "prefixlen": 24, "scope": "global"}
        ]
      },
      {
        "ifname": "lo",
        "operstate": "UNKNOWN",
        "mtu": 65536,
        "address": "00:00:00:00:00:00",
        "addr_info": [
          {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"}
        ]
      }
    ]"""
    def runner(args, timeout):
        if args[0] == "ip":
            return CommandResult(0, network_addresses, "")
        return fake_runner(args, timeout)

    snapshot = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=runner, now=lambda: 1234.5).discover()
    network = snapshot.evidence["network"]
    assert network["source"] == "iproute2"
    assert network["interfaces"]["eth0"]["operstate"] == "UP"
    assert network["interfaces"]["eth0"]["mtu"] == 9000
    assert network["interfaces"]["eth0"]["addresses"] == ["10.10.20.15/24"]
    assert network["network_domains"] == ["10.10.20.0/24"]
    assert network["fabric_domains"]["node-01"] == "10.10.20.0/24"

def test_nvidia_discovery_records_verified_nic_identity_and_link_capability():
    ethtool_driver = """driver: mlx5_core
version: 6.14.0
firmware-version: 32.42.1000
expansion-rom-version:
bus-info: 0000:41:00.0
supports-statistics: yes
supports-test: yes
supports-eeprom: yes
supports-register-dump: yes
supports-priv-flags: yes
"""
    ethtool_link = """Settings for eth0:
	Speed: 100000Mb/s
	Duplex: Full
	Auto-negotiation: off
	Link detected: yes
"""
    network_addresses = """[
      {
        "ifname": "eth0",
        "operstate": "UP",
        "mtu": 9000,
        "address": "aa:bb:cc:dd:ee:ff",
        "addr_info": [
          {"family": "inet", "local": "10.10.20.15", "prefixlen": 24, "scope": "global"}
        ]
      }
    ]"""

    def runner(args, timeout):
        args = tuple(args)
        if args[:3] == ("ethtool", "-i", "eth0"):
            return CommandResult(0, ethtool_driver, "")
        if args[:2] == ("ethtool", "eth0"):
            return CommandResult(0, ethtool_link, "")
        if args[0] == "ip":
            return CommandResult(0, network_addresses, "")
        return fake_runner(args, timeout)

    snapshot = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=runner, now=lambda: 1234.5).discover()
    network = snapshot.evidence["network"]
    assert snapshot.nodes[0].nic_names == ("eth0",)
    assert network["link_capabilities"]["eth0"]["driver"] == "mlx5_core"
    assert network["link_capabilities"]["eth0"]["firmware_version"] == "32.42.1000"
    assert network["link_capabilities"]["eth0"]["bus_info"] == "0000:41:00.0"
    assert network["link_capabilities"]["eth0"]["speed_mbps"] == 100000
    assert network["link_capabilities"]["eth0"]["duplex"] == "full"
    assert network["link_capabilities"]["eth0"]["autonegotiation"] is False
    assert network["link_capabilities"]["eth0"]["link_detected"] is True


def test_nvidia_discovery_records_rdma_device_capability_separately_from_l3_network():
    rdma_devices = """[
      {"ifname": "mlx5_0", "node_type": "RNIC", "node_guid": "0x0011223344556677", "sys_image_guid": "0x0011223344556688", "state": "ACTIVE", "physical_state": "LINK_UP"}
    ]"""
    rdma_links = """[
      {"ifname": "mlx5_0", "state": "ACTIVE", "physical_state": "LINK_UP", "netdev": "eth0"}
    ]"""
    network_addresses = """[
      {"ifname": "eth0", "operstate": "UP", "mtu": 9000, "address": "aa:bb:cc:dd:ee:ff", "addr_info": [{"family": "inet", "local": "10.10.20.15", "prefixlen": 24, "scope": "global"}]}
    ]"""

    def runner(args, timeout):
        args = tuple(args)
        if args[:4] == ("rdma", "-j", "dev", "show"):
            return CommandResult(0, rdma_devices, "")
        if args[:4] == ("rdma", "-j", "link", "show"):
            return CommandResult(0, rdma_links, "")
        if args[0] == "ip":
            return CommandResult(0, network_addresses, "")
        return fake_runner(args, timeout)

    snapshot = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=runner, now=lambda: 1234.5).discover()
    network = snapshot.evidence["network"]
    assert network["rdma"]["source"] == "rdma-core"
    assert network["rdma"]["devices"][0]["device"] == "mlx5_0"
    assert network["rdma"]["devices"][0]["state"] == "ACTIVE"
    assert network["rdma"]["devices"][0]["physical_state"] == "LINK_UP"
    assert network["rdma"]["links"][0]["netdev"] == "eth0"
    assert network["rdma"]["links"][0]["state"] == "ACTIVE"
    assert network["rdma"]["links"][0]["physical_state"] == "LINK_UP"
    assert network["rdma"]["links"][0]["rdma_device"] == "mlx5_0"
    assert network["rdma"]["links"][0]["pci_bus_id"] is not None
    assert "fabric_domains" in network
    assert network["fabric_domains"]["node-01"] == "10.10.20.0/24"


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


def test_nvidia_runtime_rejects_successful_process_without_probe_evidence():
    with pytest.raises(NvidiaRuntimeError, match="without verified success evidence"):
        NvidiaRuntime.validate_distributed_probe_output("torchrun exited successfully", 2)


def test_nvidia_runtime_accepts_only_verified_gpu_collective_evidence():
    stdout = 'THORIO_NCCL_PROBE_OK {"backend":"nccl","collective":"all_reduce","expected_sum":3,"verified_on_gpu":true,"world_size":2}\n'
    probe = NvidiaRuntime.validate_distributed_probe_output(stdout, 2)
    assert probe["backend"] == "nccl"
    assert probe["collective"] == "all_reduce"
    assert probe["world_size"] == 2
    assert probe["verified_on_gpu"] is True


def test_nvidia_runtime_rejects_inconsistent_collective_evidence():
    stdout = 'THORIO_NCCL_PROBE_OK {"backend":"nccl","collective":"all_reduce","expected_sum":4,"verified_on_gpu":true,"world_size":2}\n'
    with pytest.raises(NvidiaRuntimeError, match="did not verify"):
        NvidiaRuntime.validate_distributed_probe_output(stdout, 2)


def test_nvidia_discovery_derives_verified_local_topology_graph():
    provider = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=fake_runner, now=lambda: 1234.5)
    snapshot = provider.discover()

    topology = snapshot.evidence["topology"]
    assert topology["source"] == "nvidia-smi topo -m"
    assert topology["gpu_ids"] == ["0", "1"]
    assert topology["gpu_uuids"] == ["GPU-aaa", "GPU-bbb"]
    assert topology["links"]["0"]["1"] == "NV18"
    assert topology["links"]["1"]["0"] == "NV18"
    assert topology["gpu_affinity"]["0"]["numa"] == 0
    assert topology["gpu_affinity"]["1"]["numa"] == 0
    assert topology["connectivity_components"] == [["0", "1"]]
