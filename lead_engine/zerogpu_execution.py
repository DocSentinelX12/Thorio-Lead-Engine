"""Safe API execution adapter for Hugging Face ZeroGPU Spaces.

ZeroGPU is an API-backed GPU execution source, not a persistent worker or
GitHub runner. This adapter never promotes a ZeroGPU call into the physical
worker inventory and never claims multi-node networking or NCCL.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from .compute_fabric import ProviderCapabilities


class ZeroGPUExecutionError(RuntimeError):
    """Raised when a ZeroGPU execution cannot be performed safely."""


@dataclass(frozen=True)
class ZeroGPUExecutionConfig:
    space_url: str
    api_name: str
    token: str
    maximum_duration_seconds: int = 60
    request_timeout_seconds: int = 30
    poll_timeout_seconds: int = 180
    poll_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.space_url.strip())
        if parsed.scheme != "https" or not parsed.netloc.endswith(".hf.space"):
            raise ValueError("space_url must be an HTTPS Hugging Face Space endpoint")
        if not self.api_name.strip() or not self.api_name.startswith("/"):
            raise ValueError("api_name must be a non-empty Gradio endpoint beginning with '/'")
        if not self.token.strip():
            raise ValueError("Hugging Face token is required")
        if self.maximum_duration_seconds < 1:
            raise ValueError("maximum_duration_seconds must be positive")
        if self.request_timeout_seconds < 1 or self.poll_timeout_seconds < 1:
            raise ValueError("request and poll timeouts must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")


class ZeroGPUExecutionProvider:
    provider_id = "huggingface-zerogpu"

    def __init__(self, config: ZeroGPUExecutionConfig, *, session: requests.Session | None = None, sleeper=time.sleep):
        self.config = config
        self._session = session or requests.Session()
        self._sleep = sleeper

    @classmethod
    def from_environment(cls) -> "ZeroGPUExecutionProvider":
        enabled = os.environ.get("THORIO_ZEROGPU_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise ZeroGPUExecutionError("THORIO_ZEROGPU_ENABLED must be enabled to register ZeroGPU")
        return cls(
            ZeroGPUExecutionConfig(
                space_url=os.environ.get("THORIO_ZEROGPU_SPACE_URL", "").strip(),
                api_name=os.environ.get("THORIO_ZEROGPU_API_NAME", "").strip(),
                token=os.environ.get("HF_TOKEN", "").strip(),
                maximum_duration_seconds=int(os.environ.get("THORIO_ZEROGPU_MAX_DURATION_SECONDS", "60")),
                request_timeout_seconds=int(os.environ.get("THORIO_ZEROGPU_REQUEST_TIMEOUT_SECONDS", "30")),
                poll_timeout_seconds=int(os.environ.get("THORIO_ZEROGPU_POLL_TIMEOUT_SECONDS", "180")),
                poll_interval_seconds=float(os.environ.get("THORIO_ZEROGPU_POLL_INTERVAL_SECONDS", "1")),
            )
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            gpu_acquisition=False,
            cuda_execution=True,
            multi_gpu=True,
            networked_multi_node=False,
            arbitrary_process=False,
            provider_api=True,
            explicit_release=False,
            physical_identity_attestation=False,
            api_gpu_execution=True,
        )

    def _quota(self) -> Mapping[str, Any]:
        try:
            from huggingface_hub import get_zero_gpu_quota
        except ImportError as exc:
            raise ZeroGPUExecutionError(
                "huggingface_hub with ZeroGPU quota support is required"
            ) from exc
        try:
            quota = get_zero_gpu_quota(token=self.config.token)
        except Exception as exc:
            raise ZeroGPUExecutionError(f"ZeroGPU quota lookup failed: {exc}") from exc
        remaining = float(getattr(quota, "remaining", 0.0))
        if remaining < self.config.maximum_duration_seconds:
            raise ZeroGPUExecutionError(
                "ZeroGPU free quota is insufficient for the configured maximum execution duration"
            )
        return {
            "base_seconds": float(getattr(quota, "base", 0.0)),
            "remaining_seconds": remaining,
            "resets_at": None if getattr(quota, "resets_at", None) is None else getattr(quota, "resets_at").isoformat(),
            "overquota_used": float(getattr(quota, "overquota_used", 0.0) or 0.0),
        }

    def health(self) -> Mapping[str, Any]:
        quota = self._quota()
        return {
            "provider_id": self.provider_id,
            "state": "available",
            "free_only": True,
            "capabilities": self.capabilities().to_dict(),
            "quota": dict(quota),
        }

    def execute(self, data: list[Any]) -> Any:
        if not isinstance(data, list):
            raise TypeError("ZeroGPU request data must be a list")
        self._quota()
        endpoint = self.config.space_url.rstrip("/") + "/gradio_api/call" + self.config.api_name
        headers = {"Authorization": f"Bearer {self.config.token}", "Content-Type": "application/json"}
        try:
            response = self._session.post(
                endpoint,
                headers=headers,
                json={"data": data},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ZeroGPUExecutionError(f"ZeroGPU submission failed: {exc}") from exc
        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            raise ZeroGPUExecutionError("ZeroGPU submission returned no event_id")
        poll_endpoint = endpoint + "/" + event_id
        deadline = time.monotonic() + self.config.poll_timeout_seconds
        while time.monotonic() < deadline:
            try:
                result = self._session.get(
                    poll_endpoint,
                    headers={"Authorization": f"Bearer {self.config.token}"},
                    timeout=self.config.request_timeout_seconds,
                    stream=True,
                )
                result.raise_for_status()
                event_name = None
                for raw_line in result.iter_lines(decode_unicode=True):
                    line = (raw_line or "").strip()
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_line = line.split(":", 1)[1].strip()
                        if event_name == "complete":
                            import json
                            try:
                                return json.loads(data_line)
                            except json.JSONDecodeError as exc:
                                raise ZeroGPUExecutionError("ZeroGPU completion payload was not valid JSON") from exc
                        if event_name == "error":
                            raise ZeroGPUExecutionError(f"ZeroGPU execution failed: {data_line}")
            except requests.RequestException as exc:
                raise ZeroGPUExecutionError(f"ZeroGPU polling failed: {exc}") from exc
            self._sleep(self.config.poll_interval_seconds)
        raise ZeroGPUExecutionError("ZeroGPU execution exceeded the polling timeout")
