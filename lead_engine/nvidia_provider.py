"""Evidence-backed NVIDIA GPU discovery for the compute fabric.

This module is deliberately a discovery boundary. It never allocates GPUs,
executes business work, or mutates Thorio state. All hardware claims originate
from local NVIDIA tooling (or an injected runner in tests).
"""
from __future__ import annotations

import csv
import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .compute_provider import ComputeProvider, ProviderResourceSnapshot
from .physical_host_discovery import PhysicalHostDiscovery
from .compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


class NvidiaDiscoveryError(RuntimeError):
    """Raised when NVIDIA hardware cannot be truthfully probed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]


class NvidiaProvider(ComputeProvider):
    """Discover physical NVIDIA GPUs from the local host."""

    provider_id = "nvidia"

    def __init__(self, *, node_id: str | None = None, domain_id: str | None = None, command: str | None = None, timeout_seconds: float = 10.0, runner: Runner | None = None, now: Callable[[], float] | None = None, physical_host_discovery: PhysicalHostDiscovery | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.node_id = (node_id or os.environ.get("THORIO_NODE_ID") or "local").strip() or "local"
        self.domain_id = (domain_id or os.environ.get("THORIO_COMPUTE_DOMAIN") or self.node_id).strip() or self.node_id
        self.command = command or os.environ.get("THORIO_NVIDIA_SMI") or "nvidia-smi"
        self.timeout_seconds = timeout_seconds
        self._runner = runner or self._run_command
        self._now = now or time.time
        self._physical_host_discovery = physical_host_discovery or PhysicalHostDiscovery()

    @staticmethod
    def _run_command(args: Sequence[str], timeout_seconds: float) -> CommandResult:
        try:
            completed = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout_seconds, check=False, env=os.environ.copy())
        except FileNotFoundError as exc:
            raise NvidiaDiscoveryError("nvidia-smi is not installed or is not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise NvidiaDiscoveryError("nvidia-smi discovery timed out") from exc
        except OSError as exc:
            raise NvidiaDiscoveryError(f"unable to execute nvidia-smi: {exc}") from exc
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    def _run(self, *args: str) -> CommandResult:
        result = self._runner((self.command, *args), self.timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            raise NvidiaDiscoveryError(f"nvidia-smi failed ({result.returncode}): {detail[:1000]}")
        return result

    @staticmethod
    def _rdma_pci_bus_id(device: str) -> str | None:
        try:
            target = (Path("/sys/class/infiniband") / device / "device").resolve()
            if target.name:
                return target.name
        except OSError:
            pass
        return None

    @staticmethod
    def _pci_hierarchy(pci_bus_id: str) -> tuple[str, ...]:
        normalized = pci_bus_id.strip().lower()
        if not normalized:
            return ()
        device = Path("/sys/bus/pci/devices") / normalized
        try:
            resolved = device.resolve()
        except OSError:
            return ()
        hierarchy: list[str] = []
        current = resolved
        while current != current.parent:
            name = current.name.lower()
            if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\\.[0-7]", name):
                hierarchy.append(name)
            current = current.parent
        return tuple(hierarchy)

    @classmethod
    def _pci_common_ancestor(cls, left_pci: str, right_pci: str) -> str | None:
        left = cls._pci_hierarchy(left_pci)
        right = cls._pci_hierarchy(right_pci)
        if not left or not right:
            return None
        right_set = set(right)
        return next((component for component in left if component in right_set), None)

    @staticmethod
    def _pci_numa_node(pci_bus_id: str) -> int | None:
        normalized = pci_bus_id.strip().lower()
        if not normalized:
            return None
        try:
            value = int((Path("/sys/bus/pci/devices") / normalized / "numa_node").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return value if value >= 0 else None

    @classmethod
    def _correlate_gpu_nic_locality(cls, gpus: Sequence[GpuResource], network: Mapping[str, object]) -> list[dict[str, object]]:
        link_capabilities = network.get("link_capabilities")
        if not isinstance(link_capabilities, Mapping):
            return []
        correlations: list[dict[str, object]] = []
        for gpu in gpus:
            if not gpu.pci_bus_id:
                continue
            gpu_numa = gpu.numa_node
            for nic, raw in sorted(link_capabilities.items(), key=lambda item: str(item[0])):
                if not isinstance(raw, Mapping):
                    continue
                nic_pci = str(raw.get("bus_info") or "").strip()
                if not nic_pci:
                    continue
                common_ancestor = cls._pci_common_ancestor(gpu.pci_bus_id, nic_pci)
                nic_numa = cls._pci_numa_node(nic_pci)
                if common_ancestor is None and gpu_numa is None and nic_numa is None:
                    continue
                correlations.append({
                    "gpu_uuid": gpu.gpu_uuid,
                    "gpu_pci_bus_id": gpu.pci_bus_id,
                    "nic": str(nic),
                    "nic_pci_bus_id": nic_pci,
                    "gpu_numa_node": gpu_numa,
                    "nic_numa_node": nic_numa,
                    "same_numa_node": gpu_numa is not None and nic_numa is not None and gpu_numa == nic_numa,
                    "shared_pci_ancestor": common_ancestor,
                    "source": "sysfs",
                })
        return correlations

    @staticmethod
    def _rdma_port_gids(device: str, port: int) -> list[str]:
        if not device or not isinstance(port, int) or port < 1:
            return []
        gids_path = Path("/sys/class/infiniband") / device / "ports" / str(port) / "gids"
        try:
            entries = sorted(
                (entry for entry in gids_path.iterdir() if entry.is_file()),
                key=lambda entry: entry.name,
            )
        except OSError:
            return []
        gids: list[str] = []
        for entry in entries:
            try:
                value = entry.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if value:
                gids.append(value)
        return gids

    def _discover_rdma(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "source": "rdma-core",
            "device_command": "rdma -j dev show",
            "link_command": "rdma -j link show",
        }
        try:
            devices_result = self._runner(("rdma", "-j", "dev", "show"), self.timeout_seconds)
            if devices_result.returncode != 0:
                detail = (devices_result.stderr or devices_result.stdout).strip().replace("\n", " ")
                return {**evidence, "error": f"RDMA device discovery failed ({devices_result.returncode}): {detail[:1000]}"}
            links_result = self._runner(("rdma", "-j", "link", "show"), self.timeout_seconds)
            if links_result.returncode != 0:
                detail = (links_result.stderr or links_result.stdout).strip().replace("\n", " ")
                return {**evidence, "error": f"RDMA link discovery failed ({links_result.returncode}): {detail[:1000]}"}
            devices = json.loads(devices_result.stdout)
            links = json.loads(links_result.stdout)
        except (json.JSONDecodeError, NvidiaDiscoveryError) as exc:
            return {**evidence, "error": f"invalid RDMA discovery evidence: {exc}"}
        if not isinstance(devices, list) or not isinstance(links, list):
            return {**evidence, "error": "RDMA discovery output is not a list"}

        normalized_devices: list[dict[str, object]] = []
        for item in devices:
            if not isinstance(item, dict):
                continue
            device = str(item.get("ifname") or item.get("device") or "").strip()
            if not device:
                continue
            normalized_devices.append({
                "device": device,
                "node_type": item.get("node_type"),
                "node_guid": item.get("node_guid"),
                "sys_image_guid": item.get("sys_image_guid"),
                "state": item.get("state"),
                "physical_state": item.get("physical_state"),
                "pci_bus_id": item.get("pci_bus_id") or self._rdma_pci_bus_id(device),
            })
        normalized_devices.sort(key=lambda item: str(item["device"]))
        pci_by_device = {
            str(item["device"]): item.get("pci_bus_id")
            for item in normalized_devices
            if item.get("pci_bus_id")
        }
        normalized_links: list[dict[str, object]] = []
        for item in links:
            if not isinstance(item, dict):
                continue
            device = str(item.get("ifname") or item.get("device") or "").strip()
            netdev = str(item.get("netdev") or "").strip()
            if not device:
                device = next(
                    (
                        str(candidate.get("ifname") or candidate.get("device"))
                        for candidate in links
                        if isinstance(candidate, dict)
                        and str(candidate.get("netdev") or "").strip() == netdev
                        and (candidate.get("ifname") or candidate.get("device"))
                    ),
                    "",
                )
            if not device:
                continue
            port = item.get("port")
            normalized_links.append({
                "rdma_device": device,
                "port": port,
                "netdev": item.get("netdev"),
                "pci_bus_id": pci_by_device.get(device),
                "state": item.get("state"),
                "physical_state": item.get("physical_state"),
                "link_layer": item.get("link_layer"),
                "gids": self._rdma_port_gids(device, port) if isinstance(port, int) else [],
            })
        normalized_links.sort(key=lambda item: (str(item.get("rdma_device")), str(item.get("netdev") or "")))
        evidence["devices"] = normalized_devices
        evidence["links"] = normalized_links
        evidence["available"] = bool(normalized_devices)
        return evidence

    def _discover_network(self) -> dict[str, object]:
        result = self._runner(("ip", "-j", "address", "show"), self.timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            return {"source": "iproute2", "error": f"ip address discovery failed ({result.returncode}): {detail[:1000]}"}
        try:
            interfaces = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return {"source": "iproute2", "error": f"invalid iproute2 JSON: {exc}"}
        if not isinstance(interfaces, list):
            return {"source": "iproute2", "error": "iproute2 address output is not a list"}
        normalized: dict[str, dict[str, object]] = {}
        domains: set[str] = set()
        for item in interfaces:
            if not isinstance(item, dict):
                continue
            name = str(item.get("ifname") or "").strip()
            if not name or name == "lo":
                continue
            addresses: list[str] = []
            for address in item.get("addr_info") or []:
                if not isinstance(address, dict) or address.get("scope") != "global":
                    continue
                local = str(address.get("local") or "").strip()
                prefixlen = address.get("prefixlen")
                if not local or not isinstance(prefixlen, int):
                    continue
                try:
                    network = ipaddress.ip_network(f"{local}/{prefixlen}", strict=False)
                except ValueError:
                    continue
                addresses.append(f"{local}/{prefixlen}")
                domains.add(str(network))
            normalized[name] = {
                "operstate": str(item.get("operstate") or "").strip(),
                "mtu": int(item.get("mtu") or 0),
                "address": str(item.get("address") or "").strip(),
                "addresses": sorted(addresses),
            }
        ordered_domains = sorted(domains)
        link_capabilities = {
            name: self._discover_ethtool_link(name, self._runner, self.timeout_seconds)
            for name in sorted(normalized)
        }
        evidence: dict[str, object] = {
            "source": "iproute2",
            "command": "ip -j address show",
            "interfaces": normalized,
            "network_domains": ordered_domains,
            "link_capabilities": link_capabilities,
        }
        if len(ordered_domains) == 1:
            evidence["fabric_domains"] = {self.node_id: ordered_domains[0]}
        return evidence

    @staticmethod
    def _parse_ethtool_key_values(text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            value = value.strip()
            if key and value:
                values[key] = value
        return values

    @classmethod
    def _discover_ethtool_link(cls, interface: str, runner: Runner, timeout_seconds: float) -> dict[str, object]:
        evidence: dict[str, object] = {"interface": interface}
        try:
            driver_result = runner(("ethtool", "-i", interface), timeout_seconds)
            if driver_result.returncode != 0:
                detail = (driver_result.stderr or driver_result.stdout).strip().replace("\n", " ")
                evidence["driver_error"] = f"ethtool driver probe failed ({driver_result.returncode}): {detail[:1000]}"
            else:
                driver = cls._parse_ethtool_key_values(driver_result.stdout)
                if driver.get("driver"):
                    evidence["driver"] = driver["driver"]
                if driver.get("firmware_version"):
                    evidence["firmware_version"] = driver["firmware_version"]
                if driver.get("bus_info"):
                    evidence["bus_info"] = driver["bus_info"]
        except NvidiaDiscoveryError as exc:
            evidence["driver_error"] = str(exc)

        try:
            link_result = runner(("ethtool", interface), timeout_seconds)
            if link_result.returncode != 0:
                detail = (link_result.stderr or link_result.stdout).strip().replace("\n", " ")
                evidence["link_error"] = f"ethtool link probe failed ({link_result.returncode}): {detail[:1000]}"
            else:
                link = cls._parse_ethtool_key_values(link_result.stdout)
                speed = link.get("speed", "")
                speed_match = re.fullmatch(r"([0-9]+)\s*Mb/s", speed, re.IGNORECASE)
                if speed_match:
                    evidence["speed_mbps"] = int(speed_match.group(1))
                duplex = link.get("duplex")
                if duplex:
                    evidence["duplex"] = duplex.lower()
                autoneg = link.get("auto_negotiation")
                if autoneg:
                    normalized_autoneg = autoneg.lower()
                    if normalized_autoneg in {"on", "yes"}:
                        evidence["autonegotiation"] = True
                    elif normalized_autoneg in {"off", "no"}:
                        evidence["autonegotiation"] = False
                detected = link.get("link_detected")
                if detected:
                    normalized_detected = detected.lower()
                    if normalized_detected in {"yes", "on", "true"}:
                        evidence["link_detected"] = True
                    elif normalized_detected in {"no", "off", "false"}:
                        evidence["link_detected"] = False
        except NvidiaDiscoveryError as exc:
            evidence["link_error"] = str(exc)
        return evidence

    @staticmethod
    def _parse_cuda_supported_version(text: str) -> str | None:
        match = re.search(r"CUDA Version\s*:\s*([0-9]+(?:\.[0-9]+)+)", text, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _normalize_header(value: str) -> str:
        return re.sub(r"\s*\[[^\]]+\]\s*$", "", value.strip())

    @classmethod
    def _parse_csv(cls, text: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        reader = csv.DictReader(StringIO(text), skipinitialspace=True)
        if not reader.fieldnames:
            return rows
        for raw in reader:
            cleaned = {cls._normalize_header(str(key)): (str(value).strip() if value is not None else "") for key, value in raw.items()}
            if any(cleaned.values()):
                rows.append(cleaned)
        return rows

    @staticmethod
    def _int_bytes(value: str) -> int:
        match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*MiB$", value.strip(), re.IGNORECASE)
        if match:
            return int(float(match.group(1)) * 1024 * 1024)
        match = re.match(r"^([0-9]+)$", value.strip())
        if match:
            return int(match.group(1)) * 1024 * 1024
        raise NvidiaDiscoveryError(f"unparseable GPU memory value: {value!r}")

    @staticmethod
    def _numa_node(pci_bus_id: str) -> int | None:
        normalized = pci_bus_id.strip().lower()
        if not normalized:
            return None
        try:
            value = int((Path("/sys/bus/pci/devices") / normalized / "numa_node").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return value if value >= 0 else None

    @staticmethod
    def _normalize_uuid(value: str) -> str:
        value = value.strip()
        if not value or value.lower() in {"n/a", "none", "unknown"}:
            raise NvidiaDiscoveryError("NVIDIA GPU UUID is missing; refusing to invent physical identity")
        return value

    @staticmethod
    def _parse_nvlink_status(text: str, gpus: Sequence[GpuResource]) -> dict[str, object]:
        """Parse current per-GPU NVLink state without inferring missing links."""
        gpu_by_id = {gpu.gpu_id: gpu for gpu in gpus}
        gpu_by_uuid = {gpu.gpu_uuid: gpu for gpu in gpus}
        current_gpu: GpuResource | None = None
        links: list[dict[str, object]] = []
        header_re = re.compile(r"^GPU\\s+(\\d+):.*?(?:\\(UUID:\\s*(GPU-[^)]+)\\))?\\s*$", re.IGNORECASE)
        link_re = re.compile(r"^\\s*Link\\s+(\\d+):\\s*(.*?)\\s*$", re.IGNORECASE)
        bandwidth_re = re.compile(r"([0-9]+(?:\\.[0-9]+)?)\\s*GB/s", re.IGNORECASE)
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            header = header_re.match(line.strip())
            if header:
                gpu_id = header.group(1)
                gpu_uuid = header.group(2)
                current_gpu = gpu_by_id.get(gpu_id) or gpu_by_uuid.get(gpu_uuid or "")
                if current_gpu is None:
                    raise NvidiaDiscoveryError(f"NVLink status references undiscovered GPU {gpu_id}")
                continue
            match = link_re.match(line)
            if not match:
                continue
            if current_gpu is None:
                raise NvidiaDiscoveryError("NVLink link row appeared before a GPU header")
            link_id = int(match.group(1))
            value = match.group(2).strip()
            lowered = value.lower()
            bandwidth_match = bandwidth_re.search(value)
            bandwidth = float(bandwidth_match.group(1)) if bandwidth_match else None
            if "inactive" in lowered:
                state = "inactive"
                bandwidth = None
            elif "sleep" in lowered:
                state = "sleep"
                bandwidth = None
            elif "active" in lowered or bandwidth_match:
                state = "active"
            else:
                state = "unknown"
            links.append({
                "gpu_id": current_gpu.gpu_id,
                "gpu_uuid": current_gpu.gpu_uuid,
                "link_id": link_id,
                "state": state,
                "bandwidth_gbps": bandwidth,
            })
        links.sort(key=lambda item: (str(item["gpu_id"]), int(item["link_id"])))
        return {"source": "nvidia-smi nvlink --status", "available": bool(links), "links": links}

    @staticmethod
    def _parse_topology_matrix(text: str, gpus: Sequence[GpuResource]) -> dict[str, object]:
        """Parse nvidia-smi's physical GPU matrix without inventing topology.

        The matrix is columnar but its affinity headings vary slightly between
        driver versions. GPU columns are therefore discovered from the header,
        while affinity data is taken only from the trailing row fields. Every
        discovered GPU must have one complete row and every pairwise link must
        be present and symmetric.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise NvidiaDiscoveryError("NVIDIA topology output is empty")
        header_index = next((i for i, line in enumerate(lines) if re.search(r"\bGPU\d+\b", line)), None)
        if header_index is None:
            raise NvidiaDiscoveryError("NVIDIA topology header is missing GPU columns")

        header_tokens = lines[header_index].split()
        gpu_ids = [token[3:] for token in header_tokens if re.fullmatch(r"GPU\d+", token)]
        expected_ids = [gpu.gpu_id for gpu in gpus]
        if gpu_ids != expected_ids:
            raise NvidiaDiscoveryError(
                f"NVIDIA topology GPU columns do not match discovery: expected {expected_ids!r}, got {gpu_ids!r}"
            )

        rows: dict[str, list[str]] = {}
        for line in lines[header_index + 1:]:
            tokens = line.split()
            if not tokens or not re.fullmatch(r"GPU\d+", tokens[0]):
                continue
            gpu_id = tokens[0][3:]
            if gpu_id in rows:
                raise NvidiaDiscoveryError(f"duplicate NVIDIA topology row for GPU {gpu_id}")
            rows[gpu_id] = tokens[1:]

        if set(rows) != set(gpu_ids):
            raise NvidiaDiscoveryError(
                f"NVIDIA topology rows are incomplete: expected {gpu_ids!r}, got {sorted(rows)!r}"
            )

        links: dict[str, dict[str, str]] = {}
        affinity: dict[str, dict[str, object]] = {}
        nvlink_pattern = re.compile(r"^NV(?:L|\d+)$", re.IGNORECASE)

        for row_gpu in gpu_ids:
            values = rows[row_gpu]
            if len(values) < len(gpu_ids) + 1:
                raise NvidiaDiscoveryError(f"NVIDIA topology row for GPU {row_gpu} is incomplete")
            link_values = values[:len(gpu_ids)]
            links[row_gpu] = dict(zip(gpu_ids, link_values, strict=True))

            trailing = values[len(gpu_ids):]
            numa_match = next((re.fullmatch(r"-?\d+", value) for value in reversed(trailing)), None)
            if numa_match is None:
                raise NvidiaDiscoveryError(f"NVIDIA topology NUMA affinity is missing for GPU {row_gpu}")
            numa_index = len(trailing) - 1 - next(
                i for i, value in enumerate(reversed(trailing)) if re.fullmatch(r"-?\d+", value)
            )
            cpu_affinity_tokens = trailing[:numa_index]
            affinity[row_gpu] = {
                "cpu_affinity": " ".join(cpu_affinity_tokens),
                "numa": int(numa_match.group(0)),
            }

        for left in gpu_ids:
            for right in gpu_ids:
                if links[left][right] != links[right][left]:
                    raise NvidiaDiscoveryError(
                        f"NVIDIA topology link is asymmetric between GPU {left} and GPU {right}"
                    )

        adjacency = {
            gpu_id: {
                other
                for other in gpu_ids
                if other != gpu_id and nvlink_pattern.fullmatch(links[gpu_id][other])
            }
            for gpu_id in gpu_ids
        }
        components: list[list[str]] = []
        unseen = set(gpu_ids)
        while unseen:
            root = min(unseen, key=lambda value: gpu_ids.index(value))
            stack = [root]
            component: list[str] = []
            unseen.remove(root)
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor in sorted(adjacency[current], key=lambda value: gpu_ids.index(value)):
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        stack.append(neighbor)
            components.append(sorted(component, key=lambda value: gpu_ids.index(value)))

        uuid_by_id = {gpu.gpu_id: gpu.gpu_uuid for gpu in gpus}
        topology_domain_by_gpu: dict[str, str] = {}
        nvlink_domain_by_gpu: dict[str, str | None] = {}
        for component in components:
            domain_key = "nvlink:" + ",".join(uuid_by_id[gpu_id] or gpu_id for gpu_id in component)
            for gpu_id in component:
                topology_domain_by_gpu[gpu_id] = domain_key
                nvlink_domain_by_gpu[gpu_id] = domain_key if len(component) > 1 else None

        return {
            "source": "nvidia-smi topo -m",
            "gpu_ids": gpu_ids,
            "gpu_uuids": [uuid_by_id[gpu_id] for gpu_id in gpu_ids],
            "links": links,
            "gpu_affinity": affinity,
            "connectivity_components": components,
            "topology_domains": topology_domain_by_gpu,
            "nvlink_domains": nvlink_domain_by_gpu,
        }

    @staticmethod
    def _apply_topology_domains(gpus: Sequence[GpuResource], topology: Mapping[str, object]) -> list[GpuResource]:
        domains = topology.get("topology_domains")
        nvlink_domains = topology.get("nvlink_domains")
        if not isinstance(domains, Mapping) or not isinstance(nvlink_domains, Mapping):
            raise NvidiaDiscoveryError("structured NVIDIA topology is missing domain mappings")
        updated: list[GpuResource] = []
        for gpu in gpus:
            updated.append(GpuResource(
                node_id=gpu.node_id, gpu_id=gpu.gpu_id, gpu_uuid=gpu.gpu_uuid, model=gpu.model,
                vram_bytes=gpu.vram_bytes, compute_capability=gpu.compute_capability,
                driver_version=gpu.driver_version, cuda_version=gpu.cuda_version,
                pci_bus_id=gpu.pci_bus_id, numa_node=gpu.numa_node,
                nvlink_domain=nvlink_domains.get(gpu.gpu_id),
                topology_domain=domains.get(gpu.gpu_id),
                health_state=gpu.health_state, availability_state=gpu.availability_state,
            ))
        return updated

    def discover(self) -> ProviderResourceSnapshot:
        observed_at = float(self._now())
        if observed_at <= 0:
            raise NvidiaDiscoveryError("discovery clock must return a positive timestamp")
        query = self._run("--query-gpu=index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id", "--format=csv,nounits")
        smi = self._run()
        rows = self._parse_csv(query.stdout)
        cuda_supported = self._parse_cuda_supported_version(smi.stdout)
        driver_versions: set[str] = set()
        gpus: list[GpuResource] = []
        seen_uuids: set[str] = set()
        for row in rows:
            gpu_id = row.get("index", "").strip()
            gpu_uuid = self._normalize_uuid(row.get("uuid", ""))
            if not gpu_id:
                raise NvidiaDiscoveryError("NVIDIA GPU index is missing")
            if gpu_uuid in seen_uuids:
                raise NvidiaDiscoveryError(f"duplicate NVIDIA GPU UUID discovered: {gpu_uuid}")
            seen_uuids.add(gpu_uuid)
            driver = row.get("driver_version", "").strip() or None
            if driver:
                driver_versions.add(driver)
            pci = row.get("pci.bus_id", "").strip() or None
            compute_capability = row.get("compute_cap", "").strip() or None
            if not compute_capability:
                raise NvidiaDiscoveryError(f"compute capability missing for GPU {gpu_uuid}")
            gpus.append(GpuResource(
                node_id=self.node_id, gpu_id=gpu_id, gpu_uuid=gpu_uuid,
                model=row.get("name", "").strip() or None, vram_bytes=self._int_bytes(row.get("memory.total", "")),
                compute_capability=compute_capability, driver_version=driver, cuda_version=None,
                pci_bus_id=pci, numa_node=self._numa_node(pci) if pci else None,
                health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
            ))
        driver_version = next(iter(driver_versions), None) if len(driver_versions) <= 1 else None

        topology = None
        topology_error = None
        try:
            topology = self._run("topo", "-m").stdout
        except NvidiaDiscoveryError as exc:
            topology_error = str(exc)

        structured_topology = None
        topology_parse_error = None
        if topology:
            try:
                structured_topology = self._parse_topology_matrix(topology, gpus)
                gpus = [GpuResource(
                node_id=g.node_id, gpu_id=g.gpu_id, gpu_uuid=g.gpu_uuid, model=g.model, vram_bytes=g.vram_bytes,
                compute_capability=g.compute_capability, driver_version=g.driver_version, cuda_version=g.cuda_version,
                pci_bus_id=g.pci_bus_id, numa_node=g.numa_node, nvlink_domain=g.nvlink_domain,
                topology_domain=g.topology_domain, topology_source="nvidia-smi topo -m",
                health_state=g.health_state, availability_state=g.availability_state,
            ) for g in self._apply_topology_domains(gpus, structured_topology)]
            except NvidiaDiscoveryError as exc:
                topology_parse_error = str(exc)

        nvlink_status = None
        nvlink_status_error = None
        try:
            nvlink_status = self._parse_nvlink_status(self._run("nvlink", "-s").stdout, gpus)
        except NvidiaDiscoveryError as exc:
            nvlink_status_error = str(exc)

        host_physical = self._physical_host_discovery.discover(node_id=self.node_id)
        network_evidence = self._discover_network()
        if isinstance(network_evidence, dict):
            network_evidence["rdma"] = self._discover_rdma()
            network_evidence["gpu_nic_locality"] = self._correlate_gpu_nic_locality(gpus, network_evidence)
            network_evidence["nvlink_status"] = nvlink_status
            network_evidence["nvlink_status_error"] = nvlink_status_error
            network_evidence["physical_fabric"] = self._physical_fabric_evidence(
                node_id=self.node_id,
                gpus=gpus,
                network=network_evidence,
                observed_at=observed_at,
                host_physical=host_physical,
                nvlink_status=nvlink_status,
            )

        toolkit_version = None
        nvcc = shutil.which(os.environ.get("THORIO_NVCC", "nvcc"))
        if nvcc:
            try:
                result = self._runner((nvcc, "--version"), self.timeout_seconds)
                if result.returncode == 0:
                    match = re.search(r"release\s+([0-9]+(?:\.[0-9]+)+)", result.stdout + "\n" + result.stderr, re.IGNORECASE)
                    toolkit_version = match.group(1) if match else None
            except (OSError, subprocess.TimeoutExpired):
                toolkit_version = None

        if toolkit_version:
            gpus = [GpuResource(
                node_id=g.node_id, gpu_id=g.gpu_id, gpu_uuid=g.gpu_uuid, model=g.model, vram_bytes=g.vram_bytes,
                compute_capability=g.compute_capability, driver_version=g.driver_version, cuda_version=toolkit_version,
                pci_bus_id=g.pci_bus_id, numa_node=g.numa_node, nvlink_domain=g.nvlink_domain,
                topology_domain=g.topology_domain, topology_source=g.topology_source, health_state=g.health_state,
                availability_state=g.availability_state,
            ) for g in gpus]

        evidence: Mapping[str, object] = {
            "source": "nvidia-smi", "nvidia_smi_command": self.command,
            "gpu_query": "index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id",
            "gpu_count": len(gpus), "driver_versions": sorted(driver_versions),
            "driver_supported_cuda_version": cuda_supported, "cuda_toolkit_version": toolkit_version,
            "cuda_version_semantics": "toolkit_only_on_gpu_resource; driver_supported_version_is_separate_evidence",
            "topology_matrix": topology, "topology_error": topology_error,
            "topology": structured_topology, "topology_parse_error": topology_parse_error,
            "network": network_evidence,
            "host_physical": host_physical,
        }
        node = NodeResource(
            node_id=self.node_id, architecture=os.uname().machine if hasattr(os, "uname") else "unknown",
            cpu=CpuResource(self.node_id, os.cpu_count() or 1, self._host_memory_bytes()),
            gpus=tuple(gpus), driver_version=driver_version, cuda_version=toolkit_version,
            nic_names=tuple(sorted(network_evidence.get("interfaces", {}).keys())) if isinstance(network_evidence.get("interfaces"), dict) else (),
            state=ResourceState.AVAILABLE,
        )
        return ProviderResourceSnapshot(provider_id=self.provider_id, domain_id=self.domain_id, observed_at=observed_at, nodes=(node,), authentication_state="authenticated", evidence=evidence)

    @staticmethod
    def _physical_fabric_evidence(
        *,
        node_id: str,
        gpus: Sequence[GpuResource],
        network: Mapping[str, object],
        observed_at: float | None = None,
        host_physical: Mapping[str, object] | None = None,
        nvlink_status: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Build the canonical physical graph from observed evidence only."""
        components: dict[str, dict[str, object]] = {}
        relationships: list[dict[str, object]] = []
        contradictions: list[dict[str, object]] = []

        def evidence_record(source: str, confidence: str = "direct_observation") -> dict[str, object]:
            record: dict[str, object] = {"source": source, "confidence": confidence}
            if observed_at is not None:
                record["observed_at"] = observed_at
            return record

        def add_component(component_type: str, identity: str, attributes: Mapping[str, object] | None = None, *, source: str = "worker-local-physical-discovery") -> None:
            identity = str(identity).strip()
            if not identity:
                return
            item = components.setdefault(
                identity,
                {
                    "component_type": component_type,
                    "identity": identity,
                    "node_id": node_id,
                    "attributes": {},
                    "evidence": evidence_record(source),
                },
            )
            if isinstance(attributes, Mapping):
                item["attributes"] = {**dict(item.get("attributes") or {}), **dict(attributes)}

        def add_relationship(relationship_type: str, source: str, target: str, evidence: Mapping[str, object]) -> None:
            if source and target:
                relationship_evidence = dict(evidence)
                relationship_evidence.setdefault("confidence", "direct_observation")
                if observed_at is not None:
                    relationship_evidence.setdefault("observed_at", observed_at)
                relationships.append({
                    "relationship_type": relationship_type,
                    "source": source,
                    "target": target,
                    "evidence": relationship_evidence,
                })

        for gpu in gpus:
            gpu_identity = f"gpu:{gpu.gpu_uuid}"
            add_component("gpu", gpu_identity, {
                "gpu_id": gpu.gpu_id,
                "pci_bus_id": gpu.pci_bus_id,
                "numa_node": gpu.numa_node,
            }, source="nvidia-smi")
            if gpu.pci_bus_id:
                pci_identity = f"pci:{gpu.pci_bus_id}"
                add_component("pci", pci_identity, source="sysfs")
                add_relationship("gpu_to_pci", gpu_identity, pci_identity, {"source": "nvidia-smi", "field": "pci.bus_id"})
            if gpu.numa_node is not None:
                numa_identity = f"numa:{gpu.numa_node}"
                add_component("numa", numa_identity, {"node": gpu.numa_node}, source="sysfs")
                add_relationship("gpu_to_numa", gpu_identity, numa_identity, {"source": "sysfs", "field": "pci.numa_node"})

        link_capabilities = network.get("link_capabilities")
        if isinstance(link_capabilities, Mapping):
            for name, raw in sorted(link_capabilities.items(), key=lambda item: str(item[0])):
                if not isinstance(raw, Mapping):
                    continue
                netdev = str(name).strip()
                pci_bus_id = str(raw.get("bus_info") or "").strip()
                if not netdev:
                    continue
                nic_identity = f"nic:{netdev}"
                add_component("nic", nic_identity, dict(raw), source="ethtool")
                if pci_bus_id:
                    pci_identity = f"pci:{pci_bus_id}"
                    add_component("pci", pci_identity, source="sysfs")
                    add_relationship("nic_to_pci", nic_identity, pci_identity, {"source": "ethtool", "field": "bus_info"})

        locality_rows = network.get("gpu_nic_locality")
        if isinstance(locality_rows, list):
            for row in locality_rows:
                if not isinstance(row, Mapping):
                    continue
                gpu_uuid = str(row.get("gpu_uuid") or "").strip()
                nic = str(row.get("nic") or "").strip()
                if not gpu_uuid or not nic:
                    continue
                if row.get("shared_pci_ancestor") is not None or row.get("same_numa_node") is True:
                    add_relationship("gpu_to_nic", f"gpu:{gpu_uuid}", f"nic:{nic}", {
                        "source": row.get("source") or "sysfs",
                        "shared_pci_ancestor": row.get("shared_pci_ancestor"),
                        "same_numa_node": row.get("same_numa_node"),
                        "gpu_pci_bus_id": row.get("gpu_pci_bus_id"),
                        "nic_pci_bus_id": row.get("nic_pci_bus_id"),
                    })

        rdma = network.get("rdma")
        if isinstance(rdma, Mapping):
            devices = rdma.get("devices")
            links = rdma.get("links")
            if isinstance(devices, list):
                for raw in devices:
                    if not isinstance(raw, Mapping):
                        continue
                    device = str(raw.get("device") or "").strip()
                    if not device:
                        continue
                    rdma_identity = f"rdma:{device}"
                    add_component("rdma_device", rdma_identity, dict(raw), source="rdma-core")
                    pci_bus_id = str(raw.get("pci_bus_id") or "").strip()
                    if pci_bus_id:
                        pci_identity = f"pci:{pci_bus_id}"
                        add_component("pci", pci_identity, source="sysfs")
                        add_relationship("rdma_device_to_pci", rdma_identity, pci_identity, {"source": "rdma-core", "field": "pci_bus_id"})
            if isinstance(links, list):
                for raw in links:
                    if not isinstance(raw, Mapping):
                        continue
                    device = str(raw.get("rdma_device") or "").strip()
                    port = raw.get("port")
                    if not device or not isinstance(port, int) or port < 1:
                        continue
                    rdma_identity = f"rdma:{device}"
                    port_identity = f"rdma:{device}:{port}"
                    add_component("rdma_port", port_identity, dict(raw), source="rdma-core")
                    add_relationship("rdma_device_to_port", rdma_identity, port_identity, {
                        "source": "rdma-core",
                        "link_layer": raw.get("link_layer"),
                        "state": raw.get("state"),
                        "physical_state": raw.get("physical_state"),
                        "gids": raw.get("gids") or [],
                    })
                    netdev = str(raw.get("netdev") or "").strip()
                    if netdev:
                        add_relationship("nic_to_rdma_device", f"nic:{netdev}", rdma_identity, {
                            "source": "rdma-core",
                            "netdev": netdev,
                            "port": port,
                            "state": raw.get("state"),
                            "physical_state": raw.get("physical_state"),
                            "link_layer": raw.get("link_layer"),
                        })

        if isinstance(nvlink_status, Mapping):
            links = nvlink_status.get("links")
            if isinstance(links, list):
                for raw in links:
                    if not isinstance(raw, Mapping):
                        continue
                    gpu_uuid = str(raw.get("gpu_uuid") or "").strip()
                    link_id = raw.get("link_id")
                    if not gpu_uuid or not isinstance(link_id, int):
                        continue
                    link_identity = f"nvlink:{gpu_uuid}:{link_id}"
                    add_component("nvlink_link", link_identity, {
                        "gpu_uuid": gpu_uuid,
                        "link_id": link_id,
                        "state": raw.get("state"),
                        "bandwidth_gbps": raw.get("bandwidth_gbps"),
                    }, source="nvidia-smi nvlink --status")
                    add_relationship("gpu_nvlink", f"gpu:{gpu_uuid}", link_identity, {
                        "source": "nvidia-smi nvlink --status",
                        "state": raw.get("state"),
                        "bandwidth_gbps": raw.get("bandwidth_gbps"),
                    })

        if isinstance(host_physical, Mapping):
            pci_section = host_physical.get("pci")
            host_devices = pci_section.get("devices") if isinstance(pci_section, Mapping) else None
            host_by_bus = {
                str(raw.get("bus_id") or "").lower(): raw
                for raw in host_devices or ()
                if isinstance(raw, Mapping) and str(raw.get("bus_id") or "").strip()
            }
            for gpu in gpus:
                if not gpu.pci_bus_id:
                    continue
                host = host_by_bus.get(gpu.pci_bus_id.lower())
                if not isinstance(host, Mapping):
                    continue
                host_numa = host.get("numa_node")
                if host_numa is not None and gpu.numa_node is not None and host_numa != gpu.numa_node:
                    contradictions.append({
                        "identity": f"gpu:{gpu.gpu_uuid}",
                        "field": "numa_node",
                        "values": [
                            {"source": "nvidia-smi", "value": gpu.numa_node},
                            {"source": "sysfs", "value": host_numa},
                        ],
                    })

        contradictions.sort(key=lambda item: (str(item["identity"]), str(item["field"])))
        return {
            "components": tuple(components[key] for key in sorted(components)),
            "relationships": tuple(relationships),
            "contradictions": tuple(contradictions),
            "evidence_source": "worker-local-physical-discovery",
            "observed_at": observed_at,
        }

    @staticmethod
    def _host_memory_bytes() -> int:
        try:
            match = re.search(r"^MemTotal:\s+(\d+)\s+kB", Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
            if match:
                return max(1, int(match.group(1)) * 1024)
        except OSError:
            pass
        return 1
