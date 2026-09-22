"""Evidence-backed NVIDIA GPU discovery for the compute fabric.

This module is deliberately a discovery boundary. It never allocates GPUs,
executes business work, or mutates Thorio state. All hardware claims originate
from local NVIDIA tooling (or an injected runner in tests).
"""
from __future__ import annotations

import csv
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

    def __init__(self, *, node_id: str | None = None, domain_id: str | None = None, command: str | None = None, timeout_seconds: float = 10.0, runner: Runner | None = None, now: Callable[[], float] | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.node_id = (node_id or os.environ.get("THORIO_NODE_ID") or "local").strip() or "local"
        self.domain_id = (domain_id or os.environ.get("THORIO_COMPUTE_DOMAIN") or self.node_id).strip() or self.node_id
        self.command = command or os.environ.get("THORIO_NVIDIA_SMI") or "nvidia-smi"
        self.timeout_seconds = timeout_seconds
        self._runner = runner or self._run_command
        self._now = now or time.time

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
        }
        node = NodeResource(
            node_id=self.node_id, architecture=os.uname().machine if hasattr(os, "uname") else "unknown",
            cpu=CpuResource(self.node_id, os.cpu_count() or 1, self._host_memory_bytes()),
            gpus=tuple(gpus), driver_version=driver_version, cuda_version=toolkit_version,
            state=ResourceState.AVAILABLE,
        )
        return ProviderResourceSnapshot(provider_id=self.provider_id, domain_id=self.domain_id, observed_at=observed_at, nodes=(node,), authentication_state="authenticated", evidence=evidence)

    @staticmethod
    def _host_memory_bytes() -> int:
        try:
            match = re.search(r"^MemTotal:\s+(\d+)\s+kB", Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
            if match:
                return max(1, int(match.group(1)) * 1024)
        except OSError:
            pass
        return 1
