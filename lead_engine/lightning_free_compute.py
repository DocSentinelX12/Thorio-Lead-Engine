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
import subprocess
import time
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
    ref: str = "main"
    free_hours_remaining: float | None = None
    offer_ttl_seconds: int = 1_200

    @classmethod
    def from_environment(cls) -> "LightningFreeComputeConfig":
        studio = os.environ.get("THORIO_LIGHTNING_STUDIO", "thorio-gpu").strip()
        machine = os.environ.get("THORIO_LIGHTNING_MACHINE", "T4").strip()
        teamspace = os.environ.get("THORIO_LIGHTNING_TEAMSPACE", "").strip() or None
        repo = os.environ.get("THORIO_LIGHTNING_REPO", cls.repo).strip()
        ref = os.environ.get("THORIO_LIGHTNING_REF", "main").strip()
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
        try:
            payload = self._ssh_bootstrap(acquisition_id)
        except Exception as exc:
            try:
                stop = getattr(studio, "stop", None)
                if callable(stop):
                    stop()
            except Exception as cleanup_exc:
                raise LightningFreeComputeError(
                    f"Lightning worker bootstrap failed and Studio cleanup failed: {type(exc).__name__}: {exc}; "
                    f"cleanup: {type(cleanup_exc).__name__}: {cleanup_exc}"
                ) from exc
            if isinstance(exc, LightningFreeComputeError):
                raise
            raise LightningFreeComputeError(f"Lightning worker bootstrap failed: {type(exc).__name__}: {exc}") from exc
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

    def _ssh_teamspace_args(self) -> list[str]:
        teamspace = self.config.teamspace
        if teamspace and "/" in teamspace:
            return ["--teamspace", teamspace]
        env_teamspace = os.environ.get("LIGHTNING_TEAMSPACE", "").strip()
        if env_teamspace and "/" in env_teamspace:
            return ["--teamspace", env_teamspace]
        org = os.environ.get("LIGHTNING_ORG", "").strip()
        if org and teamspace:
            return ["--teamspace", f"{org}/{teamspace}"]
        return []

    def _configure_ssh(self) -> None:
        command = ["lightning", "ssh", "configure", "--name", self.config.studio_name]
        command.extend(self._ssh_teamspace_args())
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LightningFreeComputeError(f"Lightning SSH configuration failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-4000:]
            raise LightningFreeComputeError(
                f"Lightning SSH configuration failed with exit code {result.returncode}: {detail}"
            )

    @staticmethod
    def _ssh_connection_target(alias: str) -> Mapping[str, Any]:
        try:
            result = subprocess.run(
                ["ssh", "-G", alias], capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LightningFreeComputeError(f"Lightning SSH target resolution failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-4000:]
            raise LightningFreeComputeError(
                f"Lightning SSH target resolution failed with exit code {result.returncode}: {detail}"
            )
        values: dict[str, list[str]] = {}
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts
            values.setdefault(key, []).append(value.strip())
        hostname = values.get("hostname", [""])[0]
        user = values.get("user", [""])[0]
        port = values.get("port", [""])[0]
        if not hostname or not user or not port:
            raise LightningFreeComputeError("Lightning SSH configuration did not expose a complete connection target")
        identity_files = tuple(value for value in values.get("identityfile", ()) if value and value.lower() != "none")
        return {
            "alias": alias,
            "hostname": hostname,
            "user": user,
            "port": port,
            "identity_files": identity_files,
            "authentication_mode": "identity_file" if identity_files else "ssh_agent_or_provider_config",
        }

    def _ssh_bootstrap(self, acquisition_id: str) -> Mapping[str, Any]:
        self._configure_ssh()
        target = self._ssh_connection_target(self.config.studio_name)
        coordinator_url = os.environ.get("THORIO_COMPUTE_COORDINATOR_URL", "").strip()
        coordinator_token = os.environ.get("THORIO_COMPUTE_AUTH_TOKEN", "")
        if not coordinator_url or not coordinator_token:
            raise LightningFreeComputeError(
                "Coordinator enrollment credentials are required for Lightning bootstrap"
            )
        bootstrap = self._bootstrap_command(acquisition_id, coordinator_url)
        command = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=30",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            self.config.studio_name,
            bootstrap,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                input=coordinator_token,
                timeout=int(os.environ.get("THORIO_LIGHTNING_SSH_TIMEOUT_SECONDS", "900")),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LightningFreeComputeError(f"Lightning authenticated SSH session failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-4000:]
            raise LightningFreeComputeError(
                f"Lightning authenticated SSH bootstrap exited {result.returncode}: {detail}"
            )
        payload = self._parse_bootstrap_evidence(result.stdout or "")
        gpu_resources = payload.get("gpu_resources")
        execution = payload.get("physical_gpu_execution")
        worker_id = str(payload.get("worker_id") or "").strip()
        if not worker_id or not isinstance(gpu_resources, list) or not isinstance(execution, list):
            raise LightningFreeComputeError("Lightning SSH bootstrap evidence is missing worker or GPU identity")
        resource_uuids = {
            str(item.get("gpu_uuid")).strip()
            for item in gpu_resources
            if isinstance(item, Mapping) and item.get("gpu_uuid")
        }
        execution_uuids = {
            str(item.get("gpu_uuid")).strip()
            for item in execution
            if isinstance(item, Mapping) and item.get("gpu_uuid")
        }
        if not resource_uuids or resource_uuids != execution_uuids:
            raise LightningFreeComputeError(
                "Lightning SSH bootstrap evidence does not bind the physical CUDA execution to the discovered GPU identities"
            )
        if str(payload.get("acquisition_id") or "").strip() != acquisition_id:
            raise LightningFreeComputeError("Lightning SSH bootstrap evidence has the wrong acquisition identity")
        if str(payload.get("provider_id") or "").strip() != self.provider_id:
            raise LightningFreeComputeError("Lightning SSH bootstrap evidence has the wrong provider identity")
        payload = dict(payload)
        payload["ssh"] = {
            "available": True,
            "verification": "authenticated_ssh_session",
            "session_executed": True,
            "studio_name": self.config.studio_name,
            "connection_target": dict(target),
            "acquisition_id": acquisition_id,
            "worker_id": worker_id,
            "gpu_uuids": sorted(resource_uuids),
            "bootstrap_transport": "ssh",
        }
        return payload

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

    def _bootstrap_command(self, acquisition_id: str, coordinator_url: str | None = None) -> str:
        repo = shlex.quote(self.config.repo)
        ref = shlex.quote(self.config.ref)
        aid = shlex.quote(acquisition_id)
        coordinator = shlex.quote(coordinator_url) if coordinator_url else ""
        return (
            "set -eu; "
            "export THORIO_LIGHTNING_REQUIRE_COORDINATOR_ENROLLMENT=1; "
            f"export THORIO_COMPUTE_COORDINATOR_URL={coordinator}; "
            "export THORIO_COMPUTE_AUTH_TOKEN=$(cat); "
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
        enrollment = evidence.get("coordinator_enrollment")
        if not isinstance(enrollment, Mapping) or enrollment.get("attempted") is not True or enrollment.get("status") != "registered":
            raise LightningFreeComputeError("Lightning worker did not complete authenticated Thorio coordinator enrollment")
        return evidence


def register_lightning_provider(manager: Any, config: LightningFreeComputeConfig | None = None) -> LightningFreeComputeProvider:
    """Attach Lightning to the existing acquisition manager without replacing it."""
    provider = LightningFreeComputeProvider(config)
    manager.register(provider)
    return provider
