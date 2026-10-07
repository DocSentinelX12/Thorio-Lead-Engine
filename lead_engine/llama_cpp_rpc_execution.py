"""llama.cpp RPC distributed execution substrate.

This adapter drives the real llama.cpp RPC client path. It is intentionally
separate from API execution providers and from physical GPU inventory. A
successful RPC invocation proves client-side distributed execution occurred;
it does not, by itself, prove CUDA, NCCL, GPU identity, or physical inventory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


class LlamaCppRpcExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlamaCppRpcExecutionConfig:
    binary: str
    rpc_endpoints: tuple[str, ...]
    model: str
    request_timeout_seconds: int = 900
    gpu_layers: int = 99
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        binary = self.binary.strip()
        model = self.model.strip()
        endpoints = tuple(endpoint.strip() for endpoint in self.rpc_endpoints if endpoint.strip())
        if not binary:
            raise ValueError("binary is required")
        if not model:
            raise ValueError("model is required")
        if not endpoints:
            raise ValueError("at least one RPC endpoint is required")
        if self.request_timeout_seconds < 1:
            raise ValueError("request_timeout_seconds must be positive")
        if self.gpu_layers < 0:
            raise ValueError("gpu_layers must not be negative")
        for endpoint in endpoints:
            parsed = urlparse("//" + endpoint)
            if not parsed.hostname or parsed.port is None or not (1 <= parsed.port <= 65535):
                raise ValueError(f"invalid RPC endpoint: {endpoint}")
        object.__setattr__(self, "binary", binary)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "rpc_endpoints", endpoints)
        object.__setattr__(self, "extra_args", tuple(str(arg) for arg in self.extra_args))


class LlamaCppRpcExecutionProvider:
    """Run llama.cpp against one or more configured ggml RPC servers."""

    provider_id = "llama-cpp-rpc"

    def __init__(
        self,
        config: LlamaCppRpcExecutionConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.config = config
        self._runner = runner or subprocess.run

    @classmethod
    def from_environment(cls) -> "LlamaCppRpcExecutionProvider":
        enabled = os.environ.get("THORIO_LLAMA_CPP_RPC_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise LlamaCppRpcExecutionError(
                "THORIO_LLAMA_CPP_RPC_ENABLED must be enabled to register llama.cpp RPC"
            )
        endpoints = tuple(
            endpoint.strip()
            for endpoint in os.environ.get("THORIO_LLAMA_CPP_RPC_ENDPOINTS", "").split(",")
            if endpoint.strip()
        )
        if not endpoints:
            raise LlamaCppRpcExecutionError(
                "THORIO_LLAMA_CPP_RPC_ENDPOINTS must contain at least one host:port"
            )
        allow_insecure = os.environ.get(
            "THORIO_LLAMA_CPP_RPC_ALLOW_INSECURE_NETWORK", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not allow_insecure:
            remote = [endpoint for endpoint in endpoints if not cls._is_loopback_endpoint(endpoint)]
            if remote:
                raise LlamaCppRpcExecutionError(
                    "non-loopback llama.cpp RPC endpoints require "
                    "THORIO_LLAMA_CPP_RPC_ALLOW_INSECURE_NETWORK=1"
                )
        return cls(
            LlamaCppRpcExecutionConfig(
                binary=os.environ.get("THORIO_LLAMA_CPP_RPC_BINARY", "llama-cli"),
                rpc_endpoints=endpoints,
                model=os.environ.get("THORIO_LLAMA_CPP_RPC_MODEL", ""),
                request_timeout_seconds=int(
                    os.environ.get("THORIO_LLAMA_CPP_RPC_REQUEST_TIMEOUT_SECONDS", "900")
                ),
                gpu_layers=int(os.environ.get("THORIO_LLAMA_CPP_RPC_GPU_LAYERS", "99")),
                extra_args=tuple(
                    arg for arg in os.environ.get("THORIO_LLAMA_CPP_RPC_EXTRA_ARGS", "").split()
                    if arg
                ),
            )
        )

    @staticmethod
    def _is_loopback_endpoint(endpoint: str) -> bool:
        parsed = urlparse("//" + endpoint.strip())
        host = (parsed.hostname or "").lower()
        return host in {"127.0.0.1", "::1", "localhost"}

    def capabilities(self) -> dict[str, bool]:
        return {
            "distributed_execution_substrate": True,
            "remote_rpc_execution": True,
            "multi_node": len(self.config.rpc_endpoints) > 1,
            "networked_multi_node": len(self.config.rpc_endpoints) > 1,
            "physical_gpu_inventory": False,
            "gpu_acquisition": False,
            "cuda_execution": False,
            "nccl_execution": False,
            "physical_identity_attestation": False,
            "openai_compatible_api": False,
        }

    def _binary_path(self) -> str | None:
        if os.path.sep in self.config.binary:
            return self.config.binary if os.path.isfile(self.config.binary) else None
        return shutil.which(self.config.binary)

    def health(self) -> Mapping[str, Any]:
        binary = self._binary_path()
        if binary is None:
            return {
                "provider_id": self.provider_id,
                "state": "unavailable",
                "reason": "llama.cpp client binary was not found",
                "rpc_endpoints": self.config.rpc_endpoints,
                "capabilities": self.capabilities(),
            }
        try:
            result = self._runner(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=min(self.config.request_timeout_seconds, 30),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "provider_id": self.provider_id,
                "state": "unavailable",
                "reason": f"llama.cpp client check failed: {exc}",
                "rpc_endpoints": self.config.rpc_endpoints,
                "capabilities": self.capabilities(),
            }
        return {
            "provider_id": self.provider_id,
            "state": "configured" if result.returncode == 0 else "unavailable",
            "client_version_output": (result.stdout or "").strip(),
            "client_error": (result.stderr or "").strip(),
            "rpc_endpoints": self.config.rpc_endpoints,
            "capabilities": self.capabilities(),
        }

    def build_command(self, request: Mapping[str, Any]) -> list[str]:
        prompt = str(request.get("prompt") or "")
        if not prompt.strip():
            raise ValueError("llama.cpp RPC request requires a non-empty prompt")
        model = str(request.get("model") or self.config.model).strip()
        if not model:
            raise ValueError("llama.cpp RPC request requires model or configured model")
        command = [
            self.config.binary,
            "-m", model,
            "--rpc", ",".join(self.config.rpc_endpoints),
            "-ngl", str(int(request.get("gpu_layers", self.config.gpu_layers))),
            "-p", prompt,
        ]
        if "max_tokens" in request:
            max_tokens = int(request["max_tokens"])
            if max_tokens < 1:
                raise ValueError("max_tokens must be positive")
            command.extend(["-n", str(max_tokens)])
        if bool(request.get("simple_io", True)):
            command.append("--simple-io")
        command.extend(self.config.extra_args)
        return command

    def execute(self, data: list[Any]) -> dict[str, Any]:
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
            raise TypeError("llama.cpp RPC execution requires exactly one request object")
        request = dict(data[0])
        command = self.build_command(request)
        binary = self._binary_path()
        if binary is None:
            raise LlamaCppRpcExecutionError("llama.cpp client binary was not found")
        command[0] = binary
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.config.request_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LlamaCppRpcExecutionError(f"llama.cpp RPC execution failed to start: {exc}") from exc
        if result.returncode != 0:
            raise LlamaCppRpcExecutionError(
                "llama.cpp RPC execution failed "
                f"(exit={result.returncode}): {(result.stderr or result.stdout or '').strip()}"
            )
        return {
            "provider_id": self.provider_id,
            "status": "completed",
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "rpc_endpoints": self.config.rpc_endpoints,
            "model": str(request.get("model") or self.config.model),
            "capabilities": self.capabilities(),
        }
