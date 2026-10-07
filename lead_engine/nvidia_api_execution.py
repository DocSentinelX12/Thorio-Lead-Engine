"""NVIDIA hosted NIM API execution adapter."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from .compute_fabric import ProviderCapabilities


class NvidiaAPIExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NvidiaAPIExecutionConfig:
    credential: str
    model: str
    endpoint: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    request_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.credential.strip():
            raise ValueError("NVIDIA credential is required")
        if not self.model.strip():
            raise ValueError("NVIDIA model is required")
        if not self.endpoint.startswith("https://"):
            raise ValueError("NVIDIA API endpoint must use HTTPS")
        if self.request_timeout_seconds < 1:
            raise ValueError("request timeout must be positive")


class NvidiaAPIExecutionProvider:
    provider_id = "nvidia-api"

    def __init__(self, config: NvidiaAPIExecutionConfig, *, session: requests.Session | None = None):
        self.config = config
        self._session = session or requests.Session()

    @classmethod
    def from_environment(cls) -> "NvidiaAPIExecutionProvider":
        return cls(NvidiaAPIExecutionConfig(
            credential=os.environ.get("NVIDIA_API_KEY", "").strip(),
            model=os.environ.get("THORIO_NVIDIA_API_MODEL", "").strip(),
            endpoint=os.environ.get("THORIO_NVIDIA_API_ENDPOINT", "https://integrate.api.nvidia.com/v1/chat/completions").strip(),
            request_timeout_seconds=int(os.environ.get("THORIO_NVIDIA_API_TIMEOUT_SECONDS", "60")),
        ))

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            gpu_acquisition=False,
            cuda_execution=True,
            multi_gpu=False,
            networked_multi_node=False,
            arbitrary_process=False,
            provider_api=True,
            explicit_release=False,
            physical_identity_attestation=False,
            api_gpu_execution=True,
        )

    def health(self) -> Mapping[str, Any]:
        return {
            "provider_id": self.provider_id,
            "state": "configured",
            "free_only": True,
            "capabilities": self.capabilities().to_dict(),
            "model": self.config.model,
        }

    def execute(self, data: list[Any]) -> Any:
        if not isinstance(data, list):
            raise TypeError("NVIDIA API request data must be a list")
        try:
            response = self._session.post(
                self.config.endpoint,
                headers={
                    "Authorization": f"Bearer {self.config.credential}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={"model": self.config.model, "messages": data},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            raise NvidiaAPIExecutionError(f"NVIDIA API execution failed: {exc}") from exc
        if not isinstance(result, dict):
            raise NvidiaAPIExecutionError("NVIDIA API response must be a JSON object")
        return result
