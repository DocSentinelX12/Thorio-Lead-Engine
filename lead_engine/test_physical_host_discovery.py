from pathlib import Path

from .physical_host_discovery import PhysicalHostDiscovery


def test_physical_host_discovery_records_cpu_memory_storage_and_pci_evidence():
    files = {
        "/proc/meminfo": "MemTotal:       262144 kB\nMemAvailable:   200000 kB\n",
        "/sys/devices/system/cpu/online": "0-3\n",
        "/sys/devices/system/cpu/cpu0/topology/core_id": "0\n",
        "/sys/devices/system/cpu/cpu0/topology/physical_package_id": "0\n",
        "/sys/devices/system/cpu/cpu1/topology/core_id": "1\n",
        "/sys/devices/system/cpu/cpu1/topology/physical_package_id": "0\n",
        "/sys/devices/system/cpu/cpu2/topology/core_id": "0\n",
        "/sys/devices/system/cpu/cpu2/topology/physical_package_id": "1\n",
        "/sys/devices/system/cpu/cpu3/topology/core_id": "1\n",
        "/sys/devices/system/cpu/cpu3/topology/physical_package_id": "1\n",
        "/sys/block/nvme0n1/size": "2097152\n",
        "/sys/block/nvme0n1/queue/logical_block_size": "512\n",
        "/sys/block/nvme0n1/removable": "0\n",
        "/sys/block/nvme0n1/ro": "0\n",
        "/sys/block/nvme0n1/device/vendor": "0x8086\n",
        "/sys/block/nvme0n1/device/model": "NVMe Disk\n",
        "/sys/bus/pci/devices/0000:17:00.0/vendor": "0x10de\n",
        "/sys/bus/pci/devices/0000:17:00.0/device": "0x2330\n",
        "/sys/bus/pci/devices/0000:17:00.0/class": "0x030200\n",
        "/sys/bus/pci/devices/0000:17:00.0/numa_node": "0\n",
    }
    directories = {
        "/sys/block": ["nvme0n1"],
        "/sys/bus/pci/devices": ["0000:17:00.0"],
    }

    def read(path):
        key = str(path)
        if key not in files:
            raise OSError(key)
        return files[key]

    def glob(pattern):
        if pattern == "/sys/devices/system/cpu/cpu[0-9]*":
            return [Path(f"/sys/devices/system/cpu/cpu{i}") for i in range(4)]
        if pattern == "/sys/block/*":
            return [Path("/sys/block/nvme0n1")]
        if pattern == "/sys/bus/pci/devices/*":
            return [Path("/sys/bus/pci/devices/0000:17:00.0")]
        return []

    discovery = PhysicalHostDiscovery(file_reader=read, globber=glob)
    evidence = discovery.discover(node_id="node-01")

    assert evidence["source"] == "worker-local-linux-sysfs"
    assert evidence["memory"]["mem_total_bytes"] == 262144 * 1024
    assert evidence["cpu"]["logical_cpu_count"] == 4
    assert evidence["cpu"]["socket_count"] == 2
    assert evidence["cpu"]["core_count"] == 4
    assert evidence["storage"]["devices"][0]["name"] == "nvme0n1"
    assert evidence["storage"]["devices"][0]["capacity_bytes"] == 2097152 * 512
    assert evidence["pci"]["devices"][0]["bus_id"] == "0000:17:00.0"
    assert evidence["pci"]["devices"][0]["vendor_id"] == "0x10de"
    assert evidence["pci"]["devices"][0]["numa_node"] == 0
