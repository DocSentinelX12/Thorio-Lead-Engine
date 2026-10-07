"""Bothy community GPU sharing execution adapter.

Bothy proxies inference to volunteer GPU hosts using an OpenAI-compatible
endpoint. It is a remote inference route, not physical worker inventory and
not a model-parallel execution substrate.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from .compute_fabric import ProviderCapabilities


class BothyExecutionError(RuntimeError):
    """Raised when the Bothy gateway cannot safely execute a request."""


@dataclass(frozen=True)
class BothyExecutionConfig:
    base_url: str
    share_key: str
    request_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an http or https URL")
        if not self.share_key.strip():
            raise ValueError("share_key is required")
        if self.request_timeout_seconds < 1:
            raise ValueError("request_timeout_seconds must be positive")


class BothyExecutionProvider:
    provider_id = "bothy"

    def __init__(self, config: BothyExecutionConfig, *, session: requests.Session | None = None):
        self.config = config
        self._session = session or requests.Session()

    @classmethod
    def from_environment(cls) -> "BothyExecutionProvider":
        enabled = os.environ.get("THORIO_BOTHY_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise BothyExecutionError("THORIO_BOTHY_ENABLED must be enabled to register Bothy")
        return cls(
            BothyExecutionConfig(
                base_url=os.environ.get("THORIO_BOTHY_BASE_URL", "http://127.0.0.1:11223").strip(),
                share_key=os.environ.get("THORIO_BOTHY_SHARE_KEY", "").strip(),
                request_timeout_seconds=int(os.environ.get("THORIO_BOTHY_REQUEST_TIMEOUT_SECONDS", "60")),
            )
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            gpu_acquisition=False,
            cuda_execution=False,
            networked_multi_node=False,
            multi_node=False,
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
            "Authorization": f"Bearer {self.config.share_key}",
            "Content-Type": "application/json",
        }

    def health(self) -> Mapping[str, Any]:
        try:
            response = self._session.get(
                self.config.base_url.rstrip("/") + "/bothy/healthz",
                headers=self._headers(),
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BothyExecutionError(f"Bothy health check failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise BothyExecutionError("Bothy health response must be an object")
        return {
            "provider_id": self.provider_id,
            "state": "available",
            "free_only": True,
            "capabilities": self.capabilities().to_dict(),
            "health": dict(payload),
        }

    def execute(self, data: list[Any]) -> Any:
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
            raise TypeError("Bothy execution requires exactly one OpenAI-compatible request object")
        request = dict(data[0])
        if not str(request.get("model") or "").strip():
            raise ValueError("Bothy request requires a model")
        if not isinstance(request.get("messages"), list) or not request["messages"]:
            raise ValueError("Bothy request requires non-empty messages")
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
            raise BothyExecutionError(f"Bothy execution failed: {exc}") from exc
