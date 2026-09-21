"""Evidence-backed NVIDIA CUDA/NCCL execution runtime boundary.

This module never simulates accelerator capability. Verification succeeds only
when the local host exposes real NVIDIA tooling and an installed NCCL library.
Distributed execution remains a separate operation and must be invoked only
after local runtime evidence has been established.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence


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
        nccl_lines = [
            line.strip() for line in stdout.splitlines()
            if re.search(r"libnccl\.so(?:\.|\s|$)", line)
        ]
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
