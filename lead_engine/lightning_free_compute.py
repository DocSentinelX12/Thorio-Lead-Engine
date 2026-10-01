"""Lightning AI zero-cost GPU acquisition adapter.

This adapter uses the existing provider-neutral free-compute boundary. It never
purchases credits, upgrades a plan, or silently falls back to paid capacity.
The remote Studio is admitted only after worker-local CUDA discovery and the
existing physical execution probe produce evidence tied to the acquisition.

Lightning documents free individual Studios, free SSH, SDK automation, and
single-GPU free-tier capacity. Multi-node Studio training is a paid-plan
feature, so this adapter intentionally acquires one physical Studio at a time
and lets Thorio's existing fabric discover additional independent domains.
"""
from __future__ import annotations

import json
import os
import shlex
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from .free_compute_acquisition import AcquiredCompute, FreeComputeAcquisitionError, FreeComputeOffer, FreeComputeProvider


class LightningFreeComputeError(FreeComputeAcquisitionError):
    """Raised when Lightning cannot satisfy the strict zero-cost contract."""


@dataclass(frozen=True)
class LightningFreeComputeConfig:
    studio_name: str
    machine: str = "T4"
    teamspace: str | None = None
    repo: str = "https://github.com/DocSentinelX12/Thorio-Lead-Engine.git"
    ref: str = "feature/gpu-fabric-foundation"
    free_hours_remaining: float | None = None
    offer_ttl_seconds: int = 1_200

    @classmethod
    def from_environment(cls) -> "LightningFreeComputeConfig":
        studio = os.environ.get("THORIO_LIGHTNING_STUDIO", "thorio-gpu").strip()
        machine = os.environ.get("THORIO_LIGHTNING_MACHINE", "T4").strip()
        teamspace = os.environ.get("THORIO_LIGHTNING_TEAMSPACE", "").strip() or None
        repo = os.environ.get("THORIO_LIGHTNING_REPO", cls.repo).strip()
        ref = os.environ.get("THORIO_LIGHTNING_REF", "feature/gpu-fabric-foundation").strip()
        raw_hours = os.environ.get("THORIO_LIGHTNING_FREE_GPU_HOURS_REMAINING", "").strip()
        hours = None if not raw_hours else float(raw_hours)
        ttl = int(os.environ.get("THORIO_LIGHTNING_OFFER_TTL_SECONDS", "1200"))
        if not studio or not machine or not repo or not ref:
            raise LightningFreeComputeError("Lightning provider configuration is incomplete")
        if hours is not None and hours < 0:
            raise LightningFreeComputeError("THORIO_LIGHTNING_FREE_GPU_HOURS_REMAINING cannot be negative")
        if ttl <= 0:
            raise LightningFreeComputeError("THORIO_LIGHTNING_OFFER_TTL_SECONDS must be positive")
        return cls(studio, machine, teamspace, repo, ref, hours, ttl)


class LightningFreeComputeProvider(FreeComputeProvider):
    """Acquire one Lightning Studio only when the operator attests free budget."""

    provider_id = "lightning_ai"

    def __init__(self, config: LightningFreeComputeConfig | None = None, *, clock=time.time):
        self.config = config or LightningFreeComputeConfig.from_environment()
        self._clock = clock

    @classmethod
    def from_environment(cls) -> "LightningFreeComputeProvider":
        return cls(LightningFreeComputeConfig.from_environment())

    def _domain_id(self) -> str:
        teamspace = self.config.teamspace or "default"
        return f"lightning_ai:{teamspace}:{self.config.studio_name}"

    @staticmethod
    def _sdk() -> tuple[Any, Any]:
        try:
            from lightning_sdk import Machine, Studio
        except ImportError as exc:
            raise LightningFreeComputeError(
                "lightning-sdk is required on the acquisition controller; install it without changing Thorio's base dependency set"
            ) from exc
        return Machine, Studio

    def _machine(self, Machine: Any) -> Any:
        try:
            return getattr(Machine, self.config.machine)
        except AttributeError as exc:
            raise LightningFreeComputeError(f"unsupported Lightning machine type: {self.config.machine}") from exc

    def discover_free(self) -> tuple[FreeComputeOffer, ...]:
        if self.config.free_hours_remaining is None:
            raise LightningFreeComputeError(
                "Lightning free GPU budget is not attested; set THORIO_LIGHTNING_FREE_GPU_HOURS_REMAINING before discovery"
            )
        if self.config.free_hours_remaining <= 0:
            return ()
        observed = self._clock()
        offer_id = f"{self.config.studio_name}:{self.config.machine}"
        return (
            FreeComputeOffer(
                provider_id=self.provider_id,
                domain_id=self._domain_id(),
                offer_id=offer_id,
                observed_at=observed,
                expires_at=observed + self.config.offer_ttl_seconds,
                gpu_capable=True,
                no_cost=True,
                capacity_evidence={
                    "provider": "Lightning AI",
                    "machine": self.config.machine,
                    "studio_name": self.config.studio_name,
                    "teamspace": self.config.teamspace or "default",
                    "free_budget_hours_attested": self.config.free_hours_remaining,
                    "free_only_enforcement": "no_purchase_no_upgrade_no_paid_fallback",
                    "runtime": "AI Studio",
                    "ssh_available": True,
                    "source": "operator_attested_free_tier_budget",
                },
            ),
        )

    def acquire_free(self, offer: FreeComputeOffer) -> AcquiredCompute:
        if offer.provider_id != self.provider_id or offer.domain_id != self._domain_id():
            raise LightningFreeComputeError("Lightning offer identity does not match this provider domain")
        if not offer.no_cost:
            raise LightningFreeComputeError("paid Lightning capacity is forbidden")
        if self.config.free_hours_remaining is None or self.config.free_hours_remaining <= 0:
            raise LightningFreeComputeError("Lightning free GPU budget is unavailable")
        Machine, Studio = self._sdk()
        studio_kwargs: dict[str, Any] = {"name": self.config.studio_name}
        if self.config.teamspace:
            studio_kwargs["teamspace"] = self.config.teamspace
        studio = Studio(**studio_kwargs)
        machine = self._machine(Machine)
        try:
            studio.start(machine)
        except Exception as exc:
            raise LightningFreeComputeError(f"Lightning Studio start failed: {type(exc).__name__}: {exc}") from exc

        acquisition_id = self._acquisition_id(offer)
        bootstrap = self._bootstrap_command(acquisition_id)
        try:
            result = studio.run_with_exit_code(bootstrap)
        except AttributeError:
            result = studio.run(bootstrap)
        except Exception as exc:
            raise LightningFreeComputeError(f"Lightning worker bootstrap failed: {type(exc).__name__}: {exc}") from exc

        stdout = getattr(result, "stdout", None) if not isinstance(result, tuple) else result[0]
        stderr = getattr(result, "stderr", None) if not isinstance(result, tuple) else (result[1] if len(result) > 1 else "")
        exit_code = getattr(result, "exit_code", None) if not isinstance(result, tuple) else (result[2] if len(result) > 2 else 0)
        if exit_code not in (None, 0):
            raise LightningFreeComputeError(f"Lightning worker bootstrap exited {exit_code}: {(stderr or stdout or '')[-4000:]}")
        payload = self._parse_bootstrap_evidence(str(stdout or ""))
        return AcquiredCompute(
            provider_id=offer.provider_id,
            domain_id=offer.domain_id,
            offer_id=offer.offer_id,
            acquisition_id=acquisition_id,
            acquired_at=self._clock(),
            expires_at=offer.expires_at,
            gpu_capable=True,
            enrollment={
                "provider": self.provider_id,
                "studio_name": self.config.studio_name,
                "machine": self.config.machine,
                "ssh_required": True,
                "repo": self.config.repo,
                "ref": self.config.ref,
                "worker_bootstrap": payload,
                "physical_identity_required": True,
                "cuda_execution_required": True,
            },
        )

    def release_free(self, acquisition: AcquiredCompute) -> None:
        Machine, Studio = self._sdk()
        del Machine
        studio_kwargs: dict[str, Any] = {"name": self.config.studio_name}
        if self.config.teamspace:
            studio_kwargs["teamspace"] = self.config.teamspace
        studio = Studio(**studio_kwargs)
        stop = getattr(studio, "stop", None)
        if callable(stop):
            stop()

    def _bootstrap_command(self, acquisition_id: str) -> str:
        repo = shlex.quote(self.config.repo)
        ref = shlex.quote(self.config.ref)
        aid = shlex.quote(acquisition_id)
        return (
            "set -eu; "
            "rm -rf /tmp/thorio-worker; "
            f"git clone --depth 1 --branch {ref} {repo} /tmp/thorio-worker; "
            "cd /tmp/thorio-worker; "
            "python -m lead_engine.lightning_worker_bootstrap "
            f"--acquisition-id {aid}"
        )

    @staticmethod
    def _acquisition_id(offer: FreeComputeOffer) -> str:
        raw = f"{offer.provider_id}\x00{offer.domain_id}\x00{offer.offer_id}"
        import hashlib
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_bootstrap_evidence(stdout: str) -> Mapping[str, Any]:
        marker = "THORIO_LIGHTNING_WORKER_EVIDENCE "
        payload = next((line[len(marker):].strip() for line in stdout.splitlines() if line.startswith(marker)), "")
        if not payload:
            raise LightningFreeComputeError("Lightning worker bootstrap returned no physical evidence")
        try:
            evidence = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LightningFreeComputeError("Lightning worker bootstrap returned invalid evidence") from exc
        if not isinstance(evidence, dict) or evidence.get("gpu_discovery_state") != "healthy":
            raise LightningFreeComputeError("Lightning worker did not prove healthy GPU discovery")
        if not evidence.get("physical_gpu_execution"):
            raise LightningFreeComputeError("Lightning worker did not prove physical CUDA execution")
        return evidence


def register_lightning_provider(manager: Any, config: LightningFreeComputeConfig | None = None) -> LightningFreeComputeProvider:
    """Attach Lightning to the existing acquisition manager without replacing it."""
    provider = LightningFreeComputeProvider(config)
    manager.register(provider)
    return provider
