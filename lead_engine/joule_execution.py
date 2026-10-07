"""Joule community inference execution adapter.

Joule is a distributed volunteer GPU cluster exposed through an
OpenAI-compatible gateway. This adapter keeps Joule outside physical GPU
inventory and only advertises capabilities that the remote API can honestly
provide.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from .compute_fabric import ProviderCapabilities


class JouleExecutionError(RuntimeError):
    """Raised when the Joule gateway cannot safely execute a request."""


@dataclass(frozen=True)
class JouleExecutionConfig:
    base_url: str
    api_key: str
    request_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an http or https URL")
        if not self.api_key.strip():
            raise ValueError("api_key is required")
        if self.request_timeout_seconds < 1:
            raise ValueError("request_timeout_seconds must be positive")


class JouleExecutionProvider:
    provider_id = "joule"

    def __init__(self, config: JouleExecutionConfig, *, session: requests.Session | None = None):
        self.config = config
        self._session = session or requests.Session()

    @classmethod
    def from_environment(cls) -> "JouleExecutionProvider":
        enabled = os.environ.get("THORIO_JOULE_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise JouleExecutionError("THORIO_JOULE_ENABLED must be enabled to register Joule")
        return cls(
            JouleExecutionConfig(
                base_url=os.environ.get("THORIO_JOULE_BASE_URL", "http://127.0.0.1:7700").strip(),
                api_key=os.environ.get("THORIO_JOULE_API_KEY", "").strip(),
                request_timeout_seconds=int(os.environ.get("THORIO_JOULE_REQUEST_TIMEOUT_SECONDS", "60")),
            )
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            gpu_acquisition=False,
            cuda_execution=False,
            networked_multi_node=True,
            multi_node=True,
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
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def health(self) -> Mapping[str, Any]:
        try:
            response = self._session.get(
                self.config.base_url.rstrip("/") + "/healthz",
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise JouleExecutionError(f"Joule health check failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise JouleExecutionError("Joule health response must be an object")
        return {
            "provider_id": self.provider_id,
            "state": "available",
            "free_only": True,
            "capabilities": self.capabilities().to_dict(),
            "health": dict(payload),
        }

    def execute(self, data: list[Any]) -> Any:
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
            raise TypeError("Joule execution requires exactly one OpenAI-compatible request object")
        request = dict(data[0])
        if not str(request.get("model") or "").strip():
            raise ValueError("Joule request requires a model")
        if not isinstance(request.get("messages"), list) or not request["messages"]:
            raise ValueError("Joule request requires non-empty messages")
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
            raise JouleExecutionError(f"Joule execution failed: {exc}") from exc
