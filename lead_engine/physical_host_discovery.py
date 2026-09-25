"""Evidence-backed physical host inventory discovery.

This module reads Linux kernel/proc/sysfs state only. It never turns declared
configuration into hardware truth and never owns scheduling or business state.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Mapping


class PhysicalHostDiscoveryError(RuntimeError):
    """Raised when required physical host evidence is malformed."""


FileReader = Callable[[str | Path], str]
Globber = Callable[[str], list[Path]]


class PhysicalHostDiscovery:
    def __init__(self, *, file_reader: FileReader | None = None, globber: Globber | None = None):
        self._read = file_reader or self._read_file
        self._glob = globber or self._glob_paths

    @staticmethod
    def _read_file(path: str | Path) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _glob_paths(pattern: str) -> list[Path]:
        return sorted(Path("/").glob(pattern.lstrip("/")))

    @staticmethod
    def _positive_int(value: str, field: str) -> int:
        try:
            parsed = int(value.strip())
        except (TypeError, ValueError) as exc:
            raise PhysicalHostDiscoveryError(f"invalid {field}: {value!r}") from exc
        if parsed < 0:
            raise PhysicalHostDiscoveryError(f"invalid negative {field}: {parsed}")
        return parsed

    @staticmethod
    def _expand_cpu_list(value: str) -> tuple[int, ...]:
        cpus: set[int] = set()
        for token in value.strip().split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                start_raw, end_raw = token.split("-", 1)
                start, end = int(start_raw), int(end_raw)
                if start < 0 or end < start:
                    raise PhysicalHostDiscoveryError(f"invalid CPU range: {token}")
                cpus.update(range(start, end + 1))
            else:
                cpu = int(token)
                if cpu < 0:
                    raise PhysicalHostDiscoveryError(f"invalid CPU index: {token}")
                cpus.add(cpu)
        return tuple(sorted(cpus))

    def _cpu(self) -> dict[str, object]:
        online = self._expand_cpu_list(self._read("/sys/devices/system/cpu/online"))
        if not online:
            raise PhysicalHostDiscoveryError("Linux CPU online set is empty")
        records: list[dict[str, int]] = []
        cores: set[tuple[int, int]] = set()
        sockets: set[int] = set()
        for cpu in online:
            base = f"/sys/devices/system/cpu/cpu{cpu}/topology"
            core = self._positive_int(self._read(f"{base}/core_id"), f"cpu{cpu} core_id")
            package = self._positive_int(self._read(f"{base}/physical_package_id"), f"cpu{cpu} physical_package_id")
            cores.add((package, core))
            sockets.add(package)
            records.append({"logical_cpu": cpu, "core_id": core, "package_id": package})
        return {
            "online_cpus": list(online),
            "logical_cpu_count": len(online),
            "core_count": len(cores),
            "socket_count": len(sockets),
            "topology": records,
        }

    def _memory(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for line in self._read("/proc/meminfo").splitlines():
            match = re.match(r"^([A-Za-z0-9_]+):\s+(\d+)\s+kB", line)
            if match:
                values[match.group(1)] = int(match.group(2)) * 1024
        total = values.get("MemTotal")
        if not total or total <= 0:
            raise PhysicalHostDiscoveryError("physical memory total is missing")
        return {
            "mem_total_bytes": total,
            "mem_available_bytes": values.get("MemAvailable", 0),
        }

    def _storage(self) -> dict[str, object]:
        devices: list[dict[str, object]] = []
        for path in self._glob("/sys/block/*"):
            name = path.name
            if not name or name.startswith(("loop", "ram", "fd", "sr")):
                continue
            try:
                sectors = self._positive_int(self._read(path / "size"), f"{name} sectors")
                block_size = self._positive_int(self._read(path / "queue/logical_block_size"), f"{name} block size")
                removable = self._positive_int(self._read(path / "removable"), f"{name} removable")
                read_only = self._positive_int(self._read(path / "ro"), f"{name} read-only")
            except (OSError, PhysicalHostDiscoveryError):
                continue
            device: dict[str, object] = {
                "name": name,
                "capacity_bytes": sectors * block_size,
                "logical_block_size": block_size,
                "removable": bool(removable),
                "read_only": bool(read_only),
            }
            for field, relative in (("vendor", "device/vendor"), ("model", "device/model")):
                try:
                    value = self._read(path / relative).strip()
                except OSError:
                    value = ""
                if value:
                    device[field] = value
            devices.append(device)
        devices.sort(key=lambda item: str(item["name"]))
        return {"devices": devices}

    def _pci(self) -> dict[str, object]:
        devices: list[dict[str, object]] = []
        for path in self._glob("/sys/bus/pci/devices/*"):
            bus_id = path.name.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\\.[0-7]", bus_id):
                continue
            item: dict[str, object] = {"bus_id": bus_id}
            for field, relative in (
                ("vendor_id", "vendor"),
                ("device_id", "device"),
                ("class_code", "class"),
            ):
                try:
                    value = self._read(path / relative).strip().lower()
                except OSError:
                    value = ""
                if value:
                    item[field] = value
            try:
                numa = self._positive_int(self._read(path / "numa_node"), f"{bus_id} NUMA node")
                item["numa_node"] = numa
            except (OSError, PhysicalHostDiscoveryError):
                pass
            devices.append(item)
        devices.sort(key=lambda item: str(item["bus_id"]))
        return {"devices": devices}

    def discover(self, *, node_id: str) -> dict[str, object]:
        if not str(node_id).strip():
            raise ValueError("node_id is required")
        return {
            "source": "worker-local-linux-sysfs",
            "node_id": str(node_id).strip(),
            "cpu": self._cpu(),
            "memory": self._memory(),
            "storage": self._storage(),
            "pci": self._pci(),
        }
