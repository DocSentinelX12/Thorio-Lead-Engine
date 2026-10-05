"""Provider-neutral resource discovery contracts.

Provider adapters are discovery and health evidence boundaries only. They never
own Thorio business work or authoritative lead state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

from .compute_resources import NodeResource


@dataclass(frozen=True)
class ProviderResourceSnapshot:
    provider_id: str
    domain_id: str
    observed_at: float
    nodes: tuple[NodeResource, ...]
    ephemeral: bool = False
    expires_at: float | None = None
    authentication_state: str = "authenticated"
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.domain_id.strip():
            raise ValueError("domain_id is required")
        if self.observed_at <= 0:
            raise ValueError("observed_at must be positive")
        if self.expires_at is not None and self.expires_at <= 0:
            raise ValueError("expires_at must be positive")
        if self.ephemeral and self.expires_at is None:
            raise ValueError("ephemeral resources require expires_at")
        if not self.nodes:
            raise ValueError("resource snapshot must contain at least one node")


class ComputeProvider(ABC):
    """Adapter boundary for an authorized compute provider."""

    provider_id: str

    @abstractmethod
    def discover(self) -> ProviderResourceSnapshot:
        """Return observed resource and capability evidence."""
        raise NotImplementedError

    def health(self) -> Mapping[str, Any]:
        """Return provider health without changing business state."""
        return {"provider_id": self.provider_id, "state": "unknown"}

    def close(self) -> None:
        """Release provider adapter resources."""
        return None
