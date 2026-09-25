import tempfile
from types import SimpleNamespace
from pathlib import Path

import pytest

from .compute_pool import ComputePool, WorkerIdentity, local_worker_identity
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


def test_nvidia_discovery_preserves_rdma_topology_check_and_topo_evidence():
    def runner(args, _timeout):
        command = tuple(args)
        if command == ("rdma_topo", "check"):
            return CommandResult(0, "ACS check: PASS\\nIOMMU check: PASS\\n", "")
        if command == ("rdma_topo", "topo"):
            return CommandResult(0, "GPU 0 <-> mlx5_0:1\\n", "")
        return fake_runner(args, _timeout)

    provider = NvidiaProvider(runner=runner)
    evidence = provider._probe_rdma_topology()

    assert evidence["source"] == "rdma_topo"
    assert evidence["check"]["available"] is True
    assert evidence["check"]["stdout"] == "ACS check: PASS\\nIOMMU check: PASS\\n"
    assert evidence["topo"]["available"] is True
    assert evidence["topo"]["stdout"] == "GPU 0 <-> mlx5_0:1\\n"


def test_nvidia_discovery_keeps_rdma_topology_unavailable_without_inference():
    def runner(args, _timeout):
        if tuple(args) == ("rdma_topo", "check"):
            return CommandResult(127, "", "rdma_topo not found")
        if tuple(args) == ("rdma_topo", "topo"):
            raise NvidiaDiscoveryError("rdma_topo not installed")
        return fake_runner(args, _timeout)

    provider = NvidiaProvider(runner=runner)
    evidence = provider._probe_rdma_topology()

    assert evidence["check"]["available"] is False
    assert evidence["check"]["stderr"] == "rdma_topo not found"
    assert evidence["topo"]["available"] is False
    assert evidence["topo"]["error"] == "rdma_topo not installed"


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


def test_nvidia_discovery_parses_explicit_pci_acs_and_ats_state():
    output = """
0000:10:00.0 PCI bridge: Example
    ACSCtl: SrcValid+ ReqRedir+ CmpltRedir+
0000:41:00.0 Ethernet controller: Example
    ATSCtl: Enable+
"""
    parsed = NvidiaProvider._parse_pci_direct_features(output)
    assert parsed["0000:10:00.0"]["acs_enabled"] is True
    assert parsed["0000:10:00.0"]["acsctl"] == "SrcValid+ ReqRedir+ CmpltRedir+"
    assert parsed["0000:41:00.0"]["ats_enabled"] is True
    assert parsed["0000:41:00.0"]["atsctl"] == "Enable+"


def test_nvidia_discovery_preserves_unavailable_pci_direct_feature_probe():
    class StubHostDiscovery:
        def discover(self, *, node_id):
            return {"source": "worker-local-linux-sysfs", "node_id": node_id, "pci": {"devices": []}}

    def runner(args, timeout):
        if tuple(args) == ("lspci", "-D", "-vvv"):
            return CommandResult(1, "", "lspci unavailable")
        return fake_runner(args, timeout)

    snapshot = NvidiaProvider(
        node_id="node-01", domain_id="cell-01", runner=runner,
        physical_host_discovery=StubHostDiscovery(), now=lambda: 1234.5,
    ).discover()
    features = snapshot.evidence["host_physical"]["pci_direct_features"]
    assert features["available"] is False
    assert "lspci unavailable" in features["error"]

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


def test_nvidia_discovery_correlates_gpu_to_nic_pci_locality_without_inventing_fabric_affinity(monkeypatch):
    ethtool = {
        "eth0": """driver: mlx5_core
firmware-version: 32.42.1000
bus-info: 0000:41:00.0
""",
        "eth1": """driver: mlx5_core
firmware-version: 32.42.1001
bus-info: 0000:81:00.0
""",
    }
    network_addresses = """[
      {"ifname": "eth0", "operstate": "UP", "mtu": 9000, "address": "aa:bb:cc:dd:ee:ff", "addr_info": [{"family": "inet", "local": "10.10.20.15", "prefixlen": 24, "scope": "global"}]},
      {"ifname": "eth1", "operstate": "UP", "mtu": 9000, "address": "aa:bb:cc:dd:ee:11", "addr_info": [{"family": "inet", "local": "10.10.30.15", "prefixlen": 24, "scope": "global"}]}
    ]"""

    def runner(args, timeout):
        args = tuple(args)
        if args[:2] == ("ethtool", "-i"):
            return CommandResult(0, ethtool[args[2]], "")
        if args[0] == "ethtool":
            return CommandResult(0, "Settings for interface:\n\tLink detected: yes\n", "")
        if args[0] == "ip":
            return CommandResult(0, network_addresses, "")
        return fake_runner(args, timeout)

    numa_by_pci = {
        "00000000:17:00.0": 0,
        "00000000:18:00.0": 1,
        "0000:41:00.0": 0,
        "0000:81:00.0": 2,
    }
    monkeypatch.setattr(NvidiaProvider, "_numa_node", staticmethod(lambda pci: numa_by_pci.get(pci)))
    monkeypatch.setattr(NvidiaProvider, "_pci_numa_node", staticmethod(lambda pci: numa_by_pci.get(pci)))
    monkeypatch.setattr(
        NvidiaProvider,
        "_pci_common_ancestor",
        classmethod(
            lambda cls, left, right: "0000:40:00.0" if {left, right} == {"00000000:17:00.0", "0000:41:00.0"} else None
        ),
    )

    snapshot = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=runner, now=lambda: 1234.5).discover()
    locality = snapshot.evidence["network"]["gpu_nic_locality"]

    match = next(item for item in locality if item["gpu_uuid"] == "GPU-aaa" and item["nic"] == "eth0")
    assert match["gpu_pci_bus_id"] == "00000000:17:00.0"
    assert match["nic_pci_bus_id"] == "0000:41:00.0"
    assert match["shared_pci_ancestor"] == "0000:40:00.0"
    assert match["gpu_numa_node"] == 0
    assert match["nic_numa_node"] == 0
    assert match["same_numa_node"] is True
    assert match["source"] == "sysfs"
    assert not any(item["gpu_uuid"] == "GPU-bbb" and item["nic"] == "eth1" and item["shared_pci_ancestor"] for item in locality)


def test_nvidia_discovery_records_rdma_device_capability_separately_from_l3_network():
    rdma_devices = """[
      {"ifname": "mlx5_0", "node_type": "RNIC", "node_guid": "0x0011223344556677", "sys_image_guid": "0x0011223344556688", "state": "ACTIVE", "physical_state": "LINK_UP", "pci_bus_id": "0000:41:00.0"}
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
    assert network["rdma"]["devices"][0]["pci_bus_id"] == "0000:41:00.0"
    assert network["rdma"]["links"][0]["netdev"] == "eth0"
    assert network["rdma"]["links"][0]["state"] == "ACTIVE"
    assert network["rdma"]["links"][0]["physical_state"] == "LINK_UP"
    assert network["rdma"]["links"][0]["rdma_device"] == "mlx5_0"
    assert network["rdma"]["links"][0]["pci_bus_id"] is not None
    assert "fabric_domains" in network
    assert network["fabric_domains"]["node-01"] == "10.10.20.0/24"



def test_nvidia_discovery_preserves_verified_rdma_port_gids_and_netdev_identity(monkeypatch):
    rdma_devices = """[
      {"ifname":"mlx5_0","node_type":"RNIC","state":"ACTIVE","physical_state":"LINK_UP","pci_bus_id":"0000:41:00.0"}
    ]"""
    rdma_links = """[
      {"ifname":"mlx5_0","port":1,"state":"ACTIVE","physical_state":"LINK_UP","link_layer":"InfiniBand","netdev":"ib0"}
    ]"""
    network_addresses = """[
      {"ifname":"ib0","operstate":"UP","mtu":4092,"address":"aa:bb:cc:dd:ee:ff",
       "addr_info":[{"family":"inet","local":"10.10.20.15","prefixlen":24,"scope":"global"}]}
    ]"""

    def runner(args, timeout):
        args=tuple(args)
        if args[:4] == ("rdma","-j","dev","show"):
            return CommandResult(0, rdma_devices, "")
        if args[:4] == ("rdma","-j","link","show"):
            return CommandResult(0, rdma_links, "")
        if args[0] == "ip":
            return CommandResult(0, network_addresses, "")
        return fake_runner(args, timeout)

    monkeypatch.setattr(
        NvidiaProvider,
        "_rdma_port_gids",
        staticmethod(lambda device, port: ["fe80:0000:0000:0000:0011:2233:4455:6677", "0000:0000:0000:0000:0011:2233:4455:6688"]),
    )
    snapshot=NvidiaProvider(node_id="node-01",domain_id="cell-01",runner=runner,now=lambda:1234.5).discover()
    link=snapshot.evidence["network"]["rdma"]["links"][0]
    assert link["rdma_device"]=="mlx5_0"
    assert link["port"]==1
    assert link["link_layer"]=="InfiniBand"
    assert link["netdev"]=="ib0"
    assert link["gids"] == [
        "fe80:0000:0000:0000:0011:2233:4455:6677",
        "0000:0000:0000:0000:0011:2233:4455:6688",
    ]

def test_local_worker_identity_persists_discovered_nic_names(monkeypatch):
    node = SimpleNamespace(gpus=(), driver_version=None, cuda_version=None, nic_names=("eth0", "ib0"))
    snapshot = SimpleNamespace(nodes=(node,))
    monkeypatch.setattr(NvidiaProvider, "discover", lambda self: snapshot)

    identity = local_worker_identity("node-01")

    assert identity.nic_names == ("eth0", "ib0")


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


def test_nvidia_discovery_carries_physical_host_inventory_into_snapshot_evidence(monkeypatch):
    host_evidence = {
        "source": "worker-local-linux-sysfs",
        "node_id": "node-01",
        "cpu": {"logical_cpu_count": 4, "core_count": 4, "socket_count": 2, "online_cpus": [0, 1, 2, 3], "topology": []},
        "memory": {"mem_total_bytes": 268435456},
        "storage": {"devices": [{"name": "nvme0n1", "capacity_bytes": 1073741824}]},
        "pci": {"devices": [{"bus_id": "0000:17:00.0", "vendor_id": "0x10de", "device_id": "0x2330", "class_code": "0x030200", "numa_node": 0}]},
    }

    class StubHostDiscovery:
        def discover(self, *, node_id):
            assert node_id == "node-01"
            return host_evidence

    monkeypatch.setattr(
        "lead_engine.nvidia_provider.PhysicalHostDiscovery",
        lambda: StubHostDiscovery(),
    )
    snapshot = NvidiaProvider(node_id="node-01", domain_id="cell-01", runner=fake_runner, now=lambda: 1234.5).discover()

    assert snapshot.evidence["host_physical"] == host_evidence


def test_nvidia_discovery_parses_current_nvlink_state_and_bandwidth():
    output = """GPU 0: NVIDIA H100 (UUID: GPU-aaa)
 Link 0: 26.562 GB/s
 Link 1: <inactive>
GPU 1: NVIDIA H100 (UUID: GPU-bbb)
 Link 0: 26.562 GB/s
 Link 1: 25 GB/s
"""
    gpus = (
        GpuResource(
            node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
            vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
            health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
        ),
        GpuResource(
            node_id="node-01", gpu_id="1", gpu_uuid="GPU-bbb",
            vram_bytes=80 * 1024**3, pci_bus_id="0000:18:00.0", numa_node=0,
            health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
        ),
    )

    parsed = NvidiaProvider._parse_nvlink_status(output, gpus)

    assert parsed["source"] == "nvidia-smi nvlink --status"
    assert parsed["available"] is True
    assert parsed["links"] == [
        {"gpu_id": "0", "gpu_uuid": "GPU-aaa", "link_id": 0, "state": "active", "bandwidth_gbps": 26.562},
        {"gpu_id": "0", "gpu_uuid": "GPU-aaa", "link_id": 1, "state": "inactive", "bandwidth_gbps": None},
        {"gpu_id": "1", "gpu_uuid": "GPU-bbb", "link_id": 0, "state": "active", "bandwidth_gbps": 26.562},
        {"gpu_id": "1", "gpu_uuid": "GPU-bbb", "link_id": 1, "state": "active", "bandwidth_gbps": 25.0},
    ]


def test_physical_fabric_evidence_records_provenance_and_conflicts_without_overwriting_truth():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    network = {
        "link_capabilities": {
            "eth0": {"bus_info": "0000:17:00.1", "speed_mbps": 400000},
        },
        "gpu_nic_locality": [{
            "gpu_uuid": "GPU-aaa", "gpu_pci_bus_id": "0000:17:00.0",
            "nic": "eth0", "nic_pci_bus_id": "0000:17:00.1",
            "gpu_numa_node": 0, "nic_numa_node": 0,
            "same_numa_node": True, "shared_pci_ancestor": "0000:17:00.0",
            "source": "sysfs",
        }],
        "rdma": {
            "devices": [{"device": "mlx5_0", "pci_bus_id": "0000:17:00.1", "state": "ACTIVE"}],
            "links": [{
                "rdma_device": "mlx5_0", "port": 1, "netdev": "eth0",
                "pci_bus_id": "0000:17:00.1", "state": "ACTIVE",
                "physical_state": "LINK_UP", "link_layer": "Ethernet",
                "gids": ["fe80::1"],
            }],
        },
    }
    host_physical = {
        "pci": {
            "devices": [
                {"bus_id": "0000:17:00.0", "numa_node": 1},
                {"bus_id": "0000:17:00.1", "numa_node": 0},
            ]
        }
    }
    nvlink_status = {
        "source": "nvidia-smi nvlink --status",
        "available": True,
        "links": [{
            "gpu_id": "0", "gpu_uuid": "GPU-aaa", "link_id": 0,
            "state": "active", "bandwidth_gbps": 26.562,
        }],
    }

    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network=network,
        observed_at=1234.5,
        host_physical=host_physical,
        nvlink_status=nvlink_status,
    )

    gpu_component = next(item for item in evidence["components"] if item["identity"] == "gpu:GPU-aaa")
    assert gpu_component["evidence"] == {
        "source": "nvidia-smi",
        "confidence": "direct_observation",
        "observed_at": 1234.5,
    }
    assert any(item["relationship_type"] == "gpu_to_nic" for item in evidence["relationships"])
    assert any(item["relationship_type"] == "gpu_nvlink" for item in evidence["relationships"])
    assert any(item["relationship_type"] == "nic_to_rdma_device" for item in evidence["relationships"])
    assert evidence["contradictions"] == [{
        "identity": "gpu:GPU-aaa",
        "field": "numa_node",
        "values": [
            {"source": "nvidia-smi", "value": 0},
            {"source": "sysfs", "value": 1},
        ],
    }]


def test_physical_fabric_graph_exposes_explicit_gpu_peer_nvlink_relationship():
    gpu_a = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    gpu_b = GpuResource(
        node_id="node-01", gpu_id="1", gpu_uuid="GPU-bbb",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:18:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    topology = {
        "links": {
            "0": {"0": "X", "1": "NV18"},
            "1": {"0": "NV18", "1": "X"},
        }
    }
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu_a, gpu_b),
        network={},
        observed_at=1234.5,
        topology=topology,
    )
    peer_edges = [
        item for item in evidence["relationships"]
        if item["relationship_type"] == "gpu_to_gpu_nvlink"
    ]
    assert peer_edges == [{
        "relationship_type": "gpu_to_gpu_nvlink",
        "source": "gpu:GPU-aaa",
        "target": "gpu:GPU-bbb",
        "evidence": {
            "source": "nvidia-smi topo -m",
            "topology_path": "NV18",
            "symmetric": True,
            "confidence": "direct_observation",
            "observed_at": 1234.5,
        },
    }]


def test_physical_fabric_graph_does_not_invent_unknown_nvlink_peer_or_remote_path():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "gpu_nic_locality": [],
            "rdma": {
                "devices": [{"device": "mlx5_0", "pci_bus_id": "0000:41:00.0"}],
                "links": [{
                    "rdma_device": "mlx5_0", "port": 1, "netdev": "eth0",
                    "pci_bus_id": "0000:41:00.0", "state": "ACTIVE",
                }],
            },
        },
        observed_at=1234.5,
        topology={"links": {"0": {"0": "X"}}},
    )
    assert not any(
        item["relationship_type"] == "gpu_to_gpu_nvlink"
        for item in evidence["relationships"]
    )
    assert not any(
        item["relationship_type"] == "inter_node_path"
        for item in evidence["relationships"]
    )


def test_physical_fabric_graph_exposes_observed_pci_ancestry_for_gpu_and_nic():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "link_capabilities": {
                "eth0": {"bus_info": "0000:41:00.0"},
            },
            "rdma": {
                "devices": [{
                    "device": "mlx5_0",
                    "pci_bus_id": "0000:41:00.0",
                }],
                "links": [{
                    "rdma_device": "mlx5_0",
                    "port": 1,
                    "netdev": "eth0",
                    "pci_bus_id": "0000:41:00.0",
                    "state": "ACTIVE",
                }],
            },
        },
        host_physical={
            "pci": {
                "devices": [
                    {
                        "bus_id": "0000:17:00.0",
                        "numa_node": 0,
                        "parent_bus_id": "0000:10:00.0",
                        "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:17:00.0"],
                        "iommu_group": 7,
                    },
                    {
                        "bus_id": "0000:41:00.0",
                        "numa_node": 0,
                        "parent_bus_id": "0000:40:00.0",
                        "pci_path": ["0000:00:00.0", "0000:40:00.0", "0000:41:00.0"],
                        "iommu_group": 8,
                    },
                ]
            }
        },
        observed_at=1234.5,
    )
    ancestry = [
        item for item in evidence["relationships"]
        if item["relationship_type"] == "pci_parent"
    ]
    assert {
        item["source"] for item in ancestry
    } == {"pci:0000:17:00.0", "pci:0000:41:00.0"}
    assert all(
        item["evidence"]["source"] == "worker-local-linux-sysfs"
        for item in ancestry
    )



def test_physical_fabric_graph_exposes_rdma_port_pci_attachment_and_precise_nic_port_edge():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "link_capabilities": {
                "ib0": {"bus_info": "0000:41:00.0"},
            },
            "rdma": {
                "devices": [{
                    "device": "mlx5_0", "pci_bus_id": "0000:41:00.0",
                }],
                "links": [{
                    "rdma_device": "mlx5_0", "port": 1, "netdev": "ib0",
                    "pci_bus_id": "0000:41:00.0", "state": "ACTIVE",
                    "physical_state": "LINK_UP", "link_layer": "InfiniBand",
                }],
            },
        },
        observed_at=1234.5,
    )
    relationships = evidence["relationships"]
    assert any(
        item["relationship_type"] == "rdma_port_to_pci"
        and item["source"] == "rdma:mlx5_0:1"
        and item["target"] == "pci:0000:41:00.0"
        for item in relationships
    )
    assert any(
        item["relationship_type"] == "nic_to_rdma_port"
        and item["source"] == "nic:ib0"
        and item["target"] == "rdma:mlx5_0:1"
        for item in relationships
    )


def test_physical_fabric_graph_records_pci_root_complex_and_gdrdma_topology_assessment():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        driver_version="580.95.05",
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "link_capabilities": {
                "ib0": {"bus_info": "0000:41:00.0", "driver": "mlx5_core", "link_detected": True},
            },
            "gpu_nic_locality": [{
                "gpu_uuid": "GPU-aaa", "gpu_pci_bus_id": "0000:17:00.0",
                "nic": "ib0", "nic_pci_bus_id": "0000:41:00.0",
                "same_numa_node": True, "shared_pci_ancestor": "0000:10:00.0",
                "source": "sysfs",
            }],
            "rdma": {
                "links": [{
                    "rdma_device": "mlx5_0", "port": 1, "netdev": "ib0",
                    "pci_bus_id": "0000:41:00.0", "state": "ACTIVE",
                    "physical_state": "LINK_UP", "link_layer": "InfiniBand",
                }],
            },
        },
        host_physical={
            "iommu": {
                "source": "worker-local-linux-kernel",
                "kernel_cmdline": "BOOT_IMAGE=/vmlinuz iommu=pt quiet",
                "configured_mode": "passthrough",
                "configured_by": "iommu=pt",
                "iommu_groups_present": True,
                "iommu_group_count": 8,
            },
            "pci_direct_features": {
                "source": "lspci -D -vvv",
                "available": True,
                "devices": {
                    "0000:17:00.0": {"acsctl": "SrcValid+", "acs_enabled": True},
                    "0000:41:00.0": {"atsctl": "Enable+", "ats_enabled": True},
                    "0000:10:00.0": {"acsctl": "SrcValid+ ReqRedir-", "acs_enabled": True},
                },
            },
            "pci": {"devices": [
                {"bus_id": "0000:17:00.0", "numa_node": 0, "iommu_group": 7,
                 "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:17:00.0"]},
                {"bus_id": "0000:41:00.0", "numa_node": 0, "iommu_group": 8,
                 "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:41:00.0"]},
            ]}
        },
        observed_at=1234.5,
    )
    root_edges = [item for item in evidence["relationships"] if item["relationship_type"] == "pci_to_root_complex"]
    assert {item["target"] for item in root_edges} == {"pci_root_complex:0000:00:00.0"}
    assessment = next(item for item in evidence["relationships"] if item["relationship_type"] == "gpu_to_nic_gdrdma_assessment")
    assert assessment["evidence"]["pci_root_complex_match"] is True
    assert assessment["evidence"]["topology_distance"] == "PIX"
    assert assessment["evidence"]["rdma_link_active"] is True
    assert assessment["evidence"]["same_iommu_group"] is False
    assert assessment["evidence"]["iommu"]["configured_mode"] == "passthrough"
    assert assessment["evidence"]["iommu"]["source"] == "worker-local-linux-kernel"
    assert assessment["evidence"]["pci_direct_features"]["gpu"]["acs_enabled"] is True
    assert assessment["evidence"]["pci_direct_features"]["nic"]["ats_enabled"] is True
    assert assessment["evidence"]["pci_direct_features"]["shared_pci_ancestor"]["acsctl"] == "SrcValid+ ReqRedir-"
    assert assessment["evidence"]["eligibility"] == "topology_eligible"
    assert assessment["evidence"]["data_path_verified"] is False


def test_physical_fabric_graph_does_not_claim_gdrdma_eligible_across_different_root_complexes():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "link_capabilities": {"eth0": {"bus_info": "0000:41:00.0"}},
            "gpu_nic_locality": [{
                "gpu_uuid": "GPU-aaa", "gpu_pci_bus_id": "0000:17:00.0",
                "nic": "eth0", "nic_pci_bus_id": "0000:41:00.0",
                "same_numa_node": True, "shared_pci_ancestor": "0000:10:00.0",
                "source": "sysfs",
            }],
            "rdma": {"links": [{
                "rdma_device": "mlx5_0", "port": 1, "netdev": "eth0",
                "pci_bus_id": "0000:41:00.0", "state": "ACTIVE", "physical_state": "LINK_UP",
            }]},
        },
        host_physical={"pci": {"devices": [
            {"bus_id": "0000:17:00.0", "numa_node": 0, "iommu_group": 7,
             "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:17:00.0"]},
            {"bus_id": "0000:41:00.0", "numa_node": 0, "iommu_group": 8,
             "pci_path": ["0000:00:00.0", "0000:40:00.0", "0000:41:00.0"]},
        ]}},
        observed_at=1234.5,
    )
    assessments = [item for item in evidence["relationships"] if item["relationship_type"] == "gpu_to_nic_gdrdma_assessment"]
    assert assessments == []


def test_physical_fabric_graph_marks_gdrdma_unknown_when_rdma_link_state_is_not_verified():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "gpu_nic_locality": [{
                "gpu_uuid": "GPU-aaa", "gpu_pci_bus_id": "0000:17:00.0",
                "nic": "eth0", "nic_pci_bus_id": "0000:41:00.0",
                "same_numa_node": True, "shared_pci_ancestor": "0000:10:00.0",
                "source": "sysfs",
            }],
            "rdma": {"links": [{
                "rdma_device": "mlx5_0", "port": 1, "netdev": "eth0",
                "pci_bus_id": "0000:41:00.0", "state": "UNKNOWN", "physical_state": "UNKNOWN",
            }]},
        },
        host_physical={"pci": {"devices": [
            {"bus_id": "0000:17:00.0", "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:17:00.0"]},
            {"bus_id": "0000:41:00.0", "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:41:00.0"]},
        ]}},
        observed_at=1234.5,
    )
    assessment = next(item for item in evidence["relationships"] if item["relationship_type"] == "gpu_to_nic_gdrdma_assessment")
    assert assessment["evidence"]["eligibility"] == "unknown"
    assert assessment["evidence"]["data_path_verified"] is False


def test_physical_fabric_graph_exposes_only_evidence_backed_gpu_to_nic_traversal():
    gpu = GpuResource(
        node_id="node-01", gpu_id="0", gpu_uuid="GPU-aaa",
        vram_bytes=80 * 1024**3, pci_bus_id="0000:17:00.0", numa_node=0,
        health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
    )
    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-01",
        gpus=(gpu,),
        network={
            "link_capabilities": {
                "eth0": {"bus_info": "0000:41:00.0"},
                "eth1": {"bus_info": "0000:81:00.0"},
            },
            "gpu_nic_locality": [
                {
                    "gpu_uuid": "GPU-aaa", "gpu_pci_bus_id": "0000:17:00.0",
                    "nic": "eth0", "nic_pci_bus_id": "0000:41:00.0",
                    "shared_pci_ancestor": "0000:10:00.0",
                    "same_numa_node": True, "source": "sysfs",
                },
                {
                    "gpu_uuid": "GPU-aaa", "gpu_pci_bus_id": "0000:17:00.0",
                    "nic": "eth1", "nic_pci_bus_id": "0000:81:00.0",
                    "shared_pci_ancestor": None,
                    "same_numa_node": False, "source": "sysfs",
                },
            ],
        },
        host_physical={
            "pci": {
                "devices": [
                    {
                        "bus_id": "0000:17:00.0",
                        "parent_bus_id": "0000:10:00.0",
                        "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:17:00.0"],
                        "numa_node": 0,
                    },
                    {
                        "bus_id": "0000:41:00.0",
                        "parent_bus_id": "0000:10:00.0",
                        "pci_path": ["0000:00:00.0", "0000:10:00.0", "0000:41:00.0"],
                        "numa_node": 0,
                    },
                    {
                        "bus_id": "0000:81:00.0",
                        "parent_bus_id": "0000:80:00.0",
                        "pci_path": ["0000:00:00.0", "0000:80:00.0", "0000:81:00.0"],
                        "numa_node": 1,
                    },
                ]
            }
        },
        observed_at=1234.5,
    )
    paths = [
        item for item in evidence["relationships"]
        if item["relationship_type"] == "gpu_to_nic_path"
    ]
    assert paths == [{
        "relationship_type": "gpu_to_nic_path",
        "source": "gpu:GPU-aaa",
        "target": "nic:eth0",
        "evidence": {
            "source": "derived_from_worker_local_physical_evidence",
            "path_nodes": [
                "gpu:GPU-aaa", "pci:0000:17:00.0",
                "pci:0000:10:00.0", "pci:0000:41:00.0", "nic:eth0",
            ],
            "shared_pci_ancestor": "0000:10:00.0",
            "pci_root_complex": "0000:00:00.0",
            "topology_distance": "PIX",
            "confidence": "derived_from_observations",
            "observed_at": 1234.5,
        },
    }]
