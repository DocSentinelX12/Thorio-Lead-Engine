"""OpenHydra community inference execution adapter."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from .compute_fabric import ProviderCapabilities


class OpenHydraExecutionError(RuntimeError):
    """Raised when the OpenHydra gateway cannot safely execute a request."""


@dataclass(frozen=True)
class OpenHydraExecutionConfig:
    base_url: str
    api_key: str = ""
    request_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an http or https URL")
        if self.request_timeout_seconds < 1:
            raise ValueError("request_timeout_seconds must be positive")


class OpenHydraExecutionProvider:
    provider_id = "openhydra"

    def __init__(self, config: OpenHydraExecutionConfig, *, session: requests.Session | None = None):
        self.config = config
        self._session = session or requests.Session()

    @classmethod
    def from_environment(cls) -> "OpenHydraExecutionProvider":
        enabled = os.environ.get("THORIO_OPENHYDRA_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise OpenHydraExecutionError("THORIO_OPENHYDRA_ENABLED must be enabled to register OpenHydra")
        return cls(OpenHydraExecutionConfig(
            base_url=os.environ.get("THORIO_OPENHYDRA_BASE_URL", "http://127.0.0.1:16527").strip(),
            api_key=os.environ.get("THORIO_OPENHYDRA_API_KEY", "").strip(),
            request_timeout_seconds=int(os.environ.get("THORIO_OPENHYDRA_REQUEST_TIMEOUT_SECONDS", "60")),
        ))

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            gpu_acquisition=False,
            cuda_execution=False,
            networked_multi_node=False,
            arbitrary_process=False,
            provider_api=True,
            explicit_release=False,
            physical_identity_attestation=False,
            api_gpu_execution=True,
            community_inference=True,
            openai_compatible_api=True,
            peer_network=True,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def health(self) -> Mapping[str, Any]:
        try:
            response = self._session.get(
                self.config.base_url.rstrip("/") + "/health",
                headers=self._headers(),
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise OpenHydraExecutionError(f"OpenHydra health check failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise OpenHydraExecutionError("OpenHydra health response must be an object")
        return {"provider_id": self.provider_id, "state": "available", "free_only": True, "capabilities": self.capabilities().to_dict(), "health": dict(payload)}

    def execute(self, data: list[Any]) -> Any:
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
            raise TypeError("OpenHydra execution requires exactly one OpenAI-compatible request object")
        request = dict(data[0])
        if not str(request.get("model") or "").strip():
            raise ValueError("OpenHydra request requires a model")
        if not isinstance(request.get("messages"), list) or not request["messages"]:
            raise ValueError("OpenHydra request requires non-empty messages")
        try:
            response = self._session.post(
                self.config.base_url.rstrip("/") + "/v1/chat/completions",
                headers=self._headers(),
                json=request,
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise OpenHydraExecutionError(f"OpenHydra execution failed: {exc}") from exc
