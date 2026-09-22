"""Evidence-backed NVIDIA CUDA/NCCL execution runtime boundary.

This module never simulates accelerator capability. Verification succeeds only
when the local host exposes real NVIDIA tooling and an installed NCCL library.
Distributed verification invokes a real torchrun NCCL all-reduce probe.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


class NvidiaRuntimeError(RuntimeError):
    """Raised when required NVIDIA CUDA/NCCL runtime evidence is unavailable."""


@dataclass(frozen=True)
class NvidiaRuntime:
    runner: Callable[[Sequence[str], float], tuple[int, str, str]] | None = None
    which: Callable[[str], str | None] = shutil.which
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _run(self, args: Sequence[str]) -> tuple[int, str, str]:
        try:
            if self.runner is not None:
                return self.runner(args, self.timeout_seconds)
            result = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            return result.returncode, result.stdout, result.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NvidiaRuntimeError(f"runtime probe failed for {args[0]}: {exc}") from exc

    def _required_command(self, name: str) -> str:
        path = self.which(name)
        if not path:
            raise NvidiaRuntimeError(f"{name} is required for NVIDIA runtime verification")
        return path

    def verify_local(self) -> dict[str, object]:
        nvidia_smi = self._required_command("nvidia-smi")
        nvcc = self._required_command("nvcc")
        ldconfig = self._required_command("ldconfig")

        rc, stdout, stderr = self._run((nvidia_smi, "-L"))
        if rc != 0:
            raise NvidiaRuntimeError(f"nvidia-smi GPU enumeration failed: {(stderr or stdout).strip()[:1000]}")
        gpu_lines = [line.strip() for line in stdout.splitlines() if line.strip().startswith("GPU ")]
        if not gpu_lines:
            raise NvidiaRuntimeError("nvidia-smi reported no physical NVIDIA GPUs")

        rc, stdout, stderr = self._run((nvcc, "--version"))
        if rc != 0:
            raise NvidiaRuntimeError(f"nvcc verification failed: {(stderr or stdout).strip()[:1000]}")
        match = re.search(r"release\s+([0-9]+(?:\.[0-9]+)+)", stdout + "\n" + stderr, re.IGNORECASE)
        if not match:
            raise NvidiaRuntimeError("nvcc did not report a CUDA toolkit release")
        cuda_version = match.group(1)

        rc, stdout, stderr = self._run((ldconfig, "-p"))
        if rc != 0:
            raise NvidiaRuntimeError(f"ldconfig verification failed: {(stderr or stdout).strip()[:1000]}")
        nccl_lines = [line.strip() for line in stdout.splitlines() if re.search(r"libnccl\.so(?:\.|\s|$)", line)]
        if not nccl_lines:
            raise NvidiaRuntimeError("NCCL library was not found in the system linker cache")
        nccl_match = re.search(r"=>\s*(\S+libnccl\.so(?:\.[0-9]+)*)\s*$", nccl_lines[0])
        nccl_library = nccl_match.group(1) if nccl_match else nccl_lines[0]

        return {
            "verified": True,
            "gpu_count": len(gpu_lines),
            "gpu_enumeration": tuple(gpu_lines),
            "cuda_toolkit_version": cuda_version,
            "nccl_library": nccl_library,
            "evidence_source": ("nvidia-smi", "nvcc", "ldconfig"),
        }

    def verify_gpu_bindings(self, gpu_bindings: Sequence[Mapping[str, object]]) -> dict[str, object]:
        """Verify every allocated GPU index still maps to its durable UUID."""
        if not gpu_bindings:
            raise NvidiaRuntimeError("at least one GPU binding is required")
        nvidia_smi = self._required_command("nvidia-smi")
        rc, stdout, stderr = self._run((
            nvidia_smi,
            "--query-gpu=index,uuid",
            "--format=csv,noheader,nounits",
        ))
        if rc != 0:
            raise NvidiaRuntimeError(
                f"nvidia-smi GPU identity verification failed: {(stderr or stdout).strip()[:1000]}"
            )
        observed = {}
        for line in stdout.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                continue
            observed[parts[0]] = parts[1]
        expected = {}
        for binding in gpu_bindings:
            gpu_id = str(binding.get("gpu_id") or "").strip()
            gpu_uuid = str(binding.get("gpu_uuid") or "").strip()
            device_id = gpu_id if gpu_id.isdigit() else gpu_id.removeprefix("gpu-")
            if not device_id.isdigit() or not gpu_uuid:
                raise NvidiaRuntimeError(f"invalid allocated GPU identity: {gpu_id}/{gpu_uuid}")
            if device_id in expected:
                raise NvidiaRuntimeError(f"duplicate allocated NVIDIA device index: {device_id}")
            expected[device_id] = gpu_uuid
        mismatches = [
            f"{gpu_id}: expected {gpu_uuid}, observed {observed.get(gpu_id, '<missing>')}"
            for gpu_id, gpu_uuid in expected.items()
            if observed.get(gpu_id) != gpu_uuid
        ]
        if mismatches:
            raise NvidiaRuntimeError(
                "allocated NVIDIA GPU identity verification failed: " + "; ".join(mismatches)
            )
        return {"verified": True, "gpu_bindings": [dict(binding) for binding in gpu_bindings]}

    def distributed_process_command(self) -> tuple[str, ...]:
        """Return the exact command used for one manually ranked NCCL process.

        The fabric launches one process per allocated GPU. RANK/WORLD_SIZE,
        MASTER_ADDR/MASTER_PORT, and LOCAL_RANK are supplied in that process's
        environment by the worker. This avoids torchrun's homogeneous
        nproc-per-node requirement while preserving real NCCL initialization.
        """
        python = sys.executable
        if not python:
            raise NvidiaRuntimeError("current Python executable is required for distributed NVIDIA verification")
        return (python, "-m", "lead_engine.nccl_all_reduce_probe")

    def distributed_command(
        self,
        *,
        world_size: int,
        node_rank: int,
        nnodes: int,
        master_addr: str,
        master_port: int,
        rendezvous_id: str | None = None,
        process_count: int | None = None,
    ) -> tuple[str, ...]:
        if world_size < 2:
            raise ValueError("world_size must be at least 2 for distributed NCCL verification")
        if nnodes < 1 or not 0 <= node_rank < nnodes:
            raise ValueError("node_rank must be within nnodes")
        if world_size % nnodes != 0:
            raise ValueError("world_size must divide evenly across nnodes")
        resolved_process_count = process_count if process_count is not None else world_size // nnodes
        if resolved_process_count < 1 or resolved_process_count * nnodes != world_size:
            raise ValueError("process_count must multiply by nnodes to equal world_size")
        if not master_addr.strip():
            raise ValueError("master_addr is required")
        if not 1 <= master_port <= 65535:
            raise ValueError("master_port must be between 1 and 65535")
        torchrun = self._required_command("torchrun")
        command = [
            torchrun,
            f"--nproc-per-node={resolved_process_count}",
            f"--nnodes={nnodes}",
            f"--node-rank={node_rank}",
            f"--master-addr={master_addr.strip()}",
            f"--master-port={master_port}",
        ]
        if rendezvous_id:
            command.extend(["--rdzv-id", rendezvous_id, "--rdzv-backend", "c10d", "--rdzv-endpoint", f"{master_addr.strip()}:{master_port}"])
        command.extend(["-m", "lead_engine.nccl_all_reduce_probe"])
        return tuple(command)

    @staticmethod
    def parse_nccl_network_evidence(log_output: str) -> dict[str, object]:
        """Extract only explicit NCCL network-selection evidence from process logs."""
        if not isinstance(log_output, str):
            raise NvidiaRuntimeError("NCCL process log output must be text")
        transports: list[str] = []
        evidence_lines: list[str] = []
        gpu_direct_rdma = False
        for raw_line in log_output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.search(r"NCCL INFO Using network ([A-Za-z0-9_.-]+)", line, re.IGNORECASE)
            if match:
                transports.append(match.group(1))
                evidence_lines.append(line[-1000:])
            match = re.search(r"NCCL INFO NET/([A-Za-z0-9_.-]+)\s*:\s*Using\b", line, re.IGNORECASE)
            if match:
                transports.append(match.group(1))
                evidence_lines.append(line[-1000:])
            if re.search(r"GPU Direct RDMA Enabled", line, re.IGNORECASE) or re.search(r"GDRDMA", line, re.IGNORECASE):
                gpu_direct_rdma = True
                evidence_lines.append(line[-1000:])
        unique_transports = tuple(sorted({transport.strip() for transport in transports if transport.strip()}))
        if len(unique_transports) > 1:
            raise NvidiaRuntimeError(
                "NCCL reported multiple network transports for one rank: " + ", ".join(unique_transports)
            )
        return {
            "network_transport": unique_transports[0] if unique_transports else None,
            "network_evidence_lines": tuple(evidence_lines[-8:]),
            "gpu_direct_rdma": gpu_direct_rdma,
        }

    @classmethod
    def validate_nccl_transport_against_rdma(
        cls, log_output: str, rdma_evidence: Mapping[str, object]
    ) -> dict[str, object]:
        network = cls.parse_nccl_network_evidence(log_output)
        devices = rdma_evidence.get("devices") if isinstance(rdma_evidence, Mapping) else None
        if not isinstance(devices, list):
            raise NvidiaRuntimeError("RDMA evidence does not contain a device inventory")
        rdma_devices = tuple(sorted({
            str(item.get("device") or "").strip()
            for item in devices
            if isinstance(item, Mapping) and str(item.get("device") or "").strip()
        }))
        if network["network_transport"] == "IB":
            used = []
            for line in network["network_evidence_lines"]:
                used.extend(re.findall(r"\b(mlx[45]_[A-Za-z0-9_.-]+):\d+", line))
            used_devices = tuple(sorted(set(used)))
            if not used_devices:
                raise NvidiaRuntimeError("NCCL selected IB but did not expose an RDMA device in its network evidence")
            verified = tuple(device for device in used_devices if device in rdma_devices)
            if verified != used_devices:
                missing = ", ".join(device for device in used_devices if device not in rdma_devices)
                raise NvidiaRuntimeError(
                    "NCCL selected RDMA devices absent from verified host RDMA inventory: " + missing
                )
        else:
            used_devices = ()
            verified = ()
        return {
            **network,
            "rdma_devices": rdma_devices,
            "verified_rdma_devices": verified,
        }

    @staticmethod
    def validate_distributed_probe_output(
        stdout: str,
        world_size: int,
        *,
        expected_rank: int | None = None,
        expected_gpu_uuid: str | None = None,
        log_output: str | None = None,
    ) -> dict[str, object]:
        if world_size < 2:
            raise ValueError("world_size must be at least 2")
        marker = "THORIO_NCCL_PROBE_OK "
        lines = [line.strip() for line in stdout.splitlines() if line.strip().startswith(marker)]
        if not lines:
            raise NvidiaRuntimeError("distributed NCCL probe completed without verified success evidence")
        try:
            probe = json.loads(lines[-1][len(marker):])
        except json.JSONDecodeError as exc:
            raise NvidiaRuntimeError("distributed NCCL probe emitted invalid success evidence") from exc
        expected_sum = world_size * (world_size + 1) // 2
        expected_nnodes = int(probe.get("nnodes", 1))
        if expected_nnodes < 1:
            raise NvidiaRuntimeError("distributed NCCL probe reported an invalid node count")
        if (
            probe.get("backend") != "nccl"
            or probe.get("collective") != "all_reduce"
            or probe.get("verified_on_gpu") is not True
            or int(probe.get("world_size", -1)) != world_size
            or int(probe.get("expected_sum", -1)) != expected_sum
        ):
            raise NvidiaRuntimeError("distributed NCCL probe evidence did not verify the requested GPU collective")
        if expected_rank is not None and int(probe.get("rank", -1)) != expected_rank:
            raise NvidiaRuntimeError(
                f"distributed NCCL probe rank mismatch: expected {expected_rank}, got {probe.get('rank')}"
            )
        if expected_gpu_uuid is not None and str(probe.get("gpu_uuid") or "").strip() != expected_gpu_uuid:
            raise NvidiaRuntimeError(
                "distributed NCCL probe GPU UUID does not match the allocated physical GPU"
            )
        network = NvidiaRuntime.parse_nccl_network_evidence(
            log_output if log_output is not None else stdout
        )
        probe.update(network)
        if expected_nnodes > 1 and not str(probe.get("network_transport") or "").strip():
            raise NvidiaRuntimeError(
                "multi-node NCCL execution completed without explicit network transport evidence"
            )
        return probe

    def verify_distributed_nccl(
        self,
        *,
        world_size: int,
        node_rank: int,
        nnodes: int,
        master_addr: str,
        master_port: int,
    ) -> dict[str, object]:
        command = self.distributed_command(
            world_size=world_size,
            node_rank=node_rank,
            nnodes=nnodes,
            master_addr=master_addr,
            master_port=master_port,
        )
        if world_size < 2:
            raise ValueError("world_size must be at least 2")
        rc, stdout, stderr = self._run(command)
        if rc != 0:
            detail = (stderr or stdout).strip()
            raise NvidiaRuntimeError(f"distributed NCCL all-reduce probe failed: {detail[:4000]}")
        marker = "THORIO_NCCL_PROBE_OK "
        lines = [line.strip() for line in stdout.splitlines() if line.strip().startswith(marker)]
        if not lines:
            raise NvidiaRuntimeError("distributed NCCL probe completed without verified success evidence")
        try:
            probe = json.loads(lines[-1][len(marker):])
        except json.JSONDecodeError as exc:
            raise NvidiaRuntimeError("distributed NCCL probe emitted invalid success evidence") from exc
        probe["nnodes"] = nnodes
        probe = self.validate_distributed_probe_output(
            "THORIO_NCCL_PROBE_OK " + json.dumps(probe, sort_keys=True),
            world_size,
            log_output=stdout + "\n" + stderr,
        )
        return {
            "verified": True,
            "backend": "nccl",
            "world_size": world_size,
            "nnodes": nnodes,
            "node_rank": node_rank,
            "network_transport": probe["network_transport"],
            "gpu_direct_rdma": probe["gpu_direct_rdma"],
            "network_evidence_lines": probe["network_evidence_lines"],
            "probe_output": probe,
            "command": command,
        }
