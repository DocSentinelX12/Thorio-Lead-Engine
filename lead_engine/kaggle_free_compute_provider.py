"""Kaggle free GPU provider adapter.

This adapter is the concrete external-provider boundary for Kaggle's no-cost
GPU quota. It uses the official Kaggle CLI and never stores credentials in
Thorio. Provider authentication is delegated to the caller's Kaggle CLI
configuration.

The adapter intentionally stops at provider acceptance. It does not claim
worker enrollment, physical GPU discovery, CUDA execution, or NCCL evidence.
Those remain downstream trust boundaries.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .free_compute_acquisition import (
    AcquiredCompute,
    FreeComputeAcquisitionError,
    FreeComputeOffer,
    FreeComputeProvider,
    FreeComputeAcquisitionStore,
)


class KaggleFreeGPUProvider(FreeComputeProvider):
    """Acquire no-cost GPU execution through an authenticated Kaggle kernel."""

    provider_id = "kaggle"

    def __init__(
        self,
        *,
        kernel_dir: str | Path,
        domain_id: str = "kaggle-free-gpu",
        accelerator: str = "NvidiaTeslaT4",
        timeout_seconds: int = 3600,
        kaggle_binary: str = "kaggle",
        clock: Callable[[], float] = time.time,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.kernel_dir = Path(kernel_dir)
        self.domain_id = str(domain_id).strip()
        self.accelerator = str(accelerator).strip()
        self.timeout_seconds = int(timeout_seconds)
        self.kaggle_binary = str(kaggle_binary).strip()
        self._clock = clock
        self._runner = runner
        if not self.domain_id:
            raise ValueError("domain_id is required")
        if not self.accelerator:
            raise ValueError("accelerator is required")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if not self.kaggle_binary:
            raise ValueError("kaggle_binary is required")

    def _metadata(self) -> Mapping[str, Any]:
        path = self.kernel_dir / "kernel-metadata.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FreeComputeAcquisitionError(
                f"Kaggle kernel metadata is missing: {path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise FreeComputeAcquisitionError(
                f"Kaggle kernel metadata is invalid JSON: {path}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise FreeComputeAcquisitionError("Kaggle kernel metadata must be an object")
        kernel_id = str(payload.get("id") or "").strip()
        if "/" not in kernel_id:
            raise FreeComputeAcquisitionError(
                "Kaggle kernel metadata requires an owner/kernel id"
            )
        return payload

    @staticmethod
    def _run_output(result: subprocess.CompletedProcess[str]) -> str:
        return "\n".join(
            value for value in (result.stdout or "", result.stderr or "") if value
        ).strip()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [self.kaggle_binary, *args]
        try:
            result = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise FreeComputeAcquisitionError(
                f"Kaggle CLI could not be executed: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = self._run_output(result)
            raise FreeComputeAcquisitionError(
                f"Kaggle CLI command failed ({result.returncode}): {detail[:4000]}"
            )
        return result

    def _quota(self) -> Mapping[str, Any]:
        result = self._run("quota", "--format", "json")
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise FreeComputeAcquisitionError(
                "Kaggle quota command returned invalid JSON"
            ) from exc
        if isinstance(payload, Mapping):
            rows = payload.get("items") or payload.get("data") or []
        else:
            rows = payload
        if not isinstance(rows, list):
            raise FreeComputeAcquisitionError("Kaggle quota response has no quota rows")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("resource") or "").strip().upper() == "GPU":
                return row
        raise FreeComputeAcquisitionError("Kaggle account has no GPU quota information")

    @staticmethod
    def _hours(value: Any) -> float:
        text = str(value or "").strip().lower().removesuffix("h").strip()
        try:
            parsed = float(text)
        except (TypeError, ValueError) as exc:
            raise FreeComputeAcquisitionError(
                f"Kaggle GPU quota contains an invalid remaining value: {value!r}"
            ) from exc
        return max(0.0, parsed)

    def discover_free(self) -> tuple[FreeComputeOffer, ...]:
        metadata = self._metadata()
        quota = self._quota()
        remaining_hours = self._hours(quota.get("remaining"))
        if remaining_hours <= 0:
            return ()
        observed_at = self._clock()
        kernel_id = str(metadata["id"]).strip()
        offer_id = f"{kernel_id}:{self.accelerator}"
        return (
            FreeComputeOffer(
                provider_id=self.provider_id,
                domain_id=self.domain_id,
                offer_id=offer_id,
                observed_at=observed_at,
                expires_at=None,
                gpu_capable=True,
                no_cost=True,
                capacity_evidence={
                    "source": "kaggle_gpu_quota",
                    "kernel_ref": kernel_id,
                    "accelerator": self.accelerator,
                    "remaining_gpu_hours": remaining_hours,
                    "quota_total": quota.get("total"),
                    "quota_used": quota.get("used"),
                    "quota_refresh_at": quota.get("refreshAt"),
                    "provider_acceptance_required": True,
                    "physical_gpu_verification_required": True,
                },
            ),
        )

    def acquire_free(self, offer: FreeComputeOffer) -> AcquiredCompute:
        if offer.provider_id != self.provider_id:
            raise FreeComputeAcquisitionError("offer does not belong to Kaggle")
        if offer.domain_id != self.domain_id:
            raise FreeComputeAcquisitionError("offer domain does not match Kaggle adapter")
        if not offer.no_cost:
            raise FreeComputeAcquisitionError("Kaggle adapter cannot acquire paid capacity")
        expected_offer_id = f"{str(self._metadata()['id']).strip()}:{self.accelerator}"
        if offer.offer_id != expected_offer_id:
            raise FreeComputeAcquisitionError(
                "Kaggle offer does not match the configured kernel and accelerator"
            )
        acquired_at = self._clock()
        result = self._run(
            "kernels",
            "push",
            "--path",
            str(self.kernel_dir),
            "--accelerator",
            self.accelerator,
            "--timeout",
            str(self.timeout_seconds),
        )
        kernel_ref = str(self._metadata()["id"]).strip()
        acquisition_id = FreeComputeAcquisitionStore.acquisition_id(offer)
        return AcquiredCompute(
            provider_id=self.provider_id,
            domain_id=self.domain_id,
            offer_id=offer.offer_id,
            acquisition_id=acquisition_id,
            acquired_at=acquired_at,
            expires_at=acquired_at + self.timeout_seconds,
            gpu_capable=True,
            enrollment={
                "enrollment_mode": "kaggle_kernel_submission",
                "kernel_ref": kernel_ref,
                "accelerator_requested": self.accelerator,
                "timeout_seconds": self.timeout_seconds,
                "provider_submission_accepted": True,
                "provider_output": self._run_output(result)[:4000],
                "physical_gpu_verification_required": True,
            },
        )

    def release_free(self, acquisition: AcquiredCompute) -> None:
        if acquisition.provider_id != self.provider_id:
            raise FreeComputeAcquisitionError("acquisition does not belong to Kaggle")
        kernel_ref = str(acquisition.enrollment.get("kernel_ref") or "").strip()
        if not kernel_ref:
            raise FreeComputeAcquisitionError("Kaggle acquisition has no kernel reference")
        self._run("kernels", "delete", kernel_ref, "--yes")
