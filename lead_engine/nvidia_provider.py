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
    """Raised when NVIDIA hardware is present but cannot be truthfully probed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]


class NvidiaProvider(ComputeProvider):
    """Discover physical NVIDIA GPUs from the local host."""

    provider_id = "nvidia"

    def __init__(
        self,
        *,
        node_id: str | None = None,
        domain_id: str | None = None,
        command: str | None = None,
        timeout_seconds: float = 10.0,
        runner: Runner | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
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
            completed = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=os.environ.copy(),
            )
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
    def _parse_csv(text: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        reader = csv.DictReader(StringIO(text), skipinitialspace=True)
        if not reader.fieldnames:
            return rows
        for raw in reader:
            cleaned = {str(key).strip(): (str(value).strip() if value is not None else "") for key, value in raw.items()}
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
        path = Path("/sys/bus/pci/devices") / normalized
        numa = path / "numa_node"
        try:
            value = int(numa.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return value if value >= 0 else None

    @staticmethod
    def _normalize_uuid(value: str) -> str:
        value = value.strip()
        if not value or value.lower() in {"n/a", "none", "unknown"}:
            raise NvidiaDiscoveryError("NVIDIA GPU UUID is missing; refusing to invent physical identity")
        return value

    def discover(self) -> ProviderResourceSnapshot:
        observed_at = float(self._now())
        if observed_at <= 0:
            raise NvidiaDiscoveryError("discovery clock must return a positive timestamp")

        try:
            query = self._run(
                "--query-gpu=index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id",
                "--format=csv,noheader,nounits",
            )
            smi = self._run()
        except NvidiaDiscoveryError:
            # A host with no NVIDIA stack is a truthful zero-GPU observation only
            # when the command exists and reports no devices. Missing/broken
            # tooling is not silently converted into "no GPUs".
            raise

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
                node_id=self.node_id,
                gpu_id=gpu_id,
                gpu_uuid=gpu_uuid,
                model=row.get("name", "").strip() or None,
                vram_bytes=self._int_bytes(row.get("memory.total", "")),
                compute_capability=compute_capability,
                driver_version=driver,
                cuda_version=cuda_supported,
                pci_bus_id=pci,
                numa_node=self._numa_node(pci) if pci else None,
                health_state=ResourceState.HEALTHY,
                availability_state=ResourceState.AVAILABLE,
            ))

        driver_version = next(iter(driver_versions), None)
        if len(driver_versions) > 1:
            # A host can expose different driver strings only under unusual
            # virtualization. Preserve per-GPU values and refuse to flatten them.
            driver_version = None

        topology = None
        topology_error = None
        try:
            topology_result = self._run("topo", "-m")
            topology = topology_result.stdout.strip()
        except NvidiaDiscoveryError as exc:
            topology_error = str(exc)

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

        evidence: Mapping[str, object] = {
            "source": "nvidia-smi",
            "nvidia_smi_command": self.command,
            "gpu_query": "index,uuid,name,memory.total,compute_cap,driver_version,pci.bus_id",
            "gpu_count": len(gpus),
            "driver_versions": sorted(driver_versions),
            "driver_supported_cuda_version": cuda_supported,
            "cuda_toolkit_version": toolkit_version,
            "cuda_version_semantics": "driver_supported_maximum",
            "topology_matrix": topology,
            "topology_error": topology_error,
        }
        cpu_count = os.cpu_count() or 1
        memory_bytes = self._host_memory_bytes()
        node = NodeResource(
            node_id=self.node_id,
            architecture=os.uname().machine if hasattr(os, "uname") else "unknown",
            cpu=CpuResource(self.node_id, cpu_count, memory_bytes),
            gpus=tuple(gpus),
            driver_version=driver_version,
            cuda_version=toolkit_version or cuda_supported,
            state=ResourceState.AVAILABLE if gpus or not topology_error else ResourceState.DEGRADED,
        )
        return ProviderResourceSnapshot(
            provider_id=self.provider_id,
            domain_id=self.domain_id,
            observed_at=observed_at,
            nodes=(node,),
            authentication_state="authenticated",
            evidence=evidence,
        )

    @staticmethod
    def _host_memory_bytes() -> int:
        try:
            meminfo = Path("/proc/meminfo")
            match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
            if match:
                return max(1, int(match.group(1)) * 1024)
        except OSError:
            pass
        return 1
