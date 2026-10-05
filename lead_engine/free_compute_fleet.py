"""Scalable zero-cost compute fleet acquisition orchestration.

This layer sits above individual provider adapters. It turns observed provider
capacity into a durable, evidence-backed acquisition target without inventing
hardware, bypassing provider limits, or imposing an arbitrary fleet ceiling.
The existing worker enrollment, physical GPU verification, inventory, scheduler,
and fabric layers remain authoritative after acquisition.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .free_compute_acquisition import FreeComputeAcquisitionManager


class FreeComputeFleetError(ValueError):
    """Raised when a fleet target is invalid."""


@dataclass(frozen=True)
class FreeComputeFleetTarget:
    gpu_nodes: int

    def __post_init__(self) -> None:
        if isinstance(self.gpu_nodes, bool) or self.gpu_nodes < 0:
            raise FreeComputeFleetError("gpu_nodes must be zero or greater")


class FreeComputeFleetController:
    """Coordinate provider domains toward an explicit GPU-capacity target."""

    def __init__(self, acquisition: FreeComputeAcquisitionManager):
        self.acquisition = acquisition

    def status(self) -> dict[str, Any]:
        status = self.acquisition.status()
        verified_gpu = sum(
            1
            for record in status["records"]
            if record["status"] == "verified"
            and record["gpu_capable"]
            and (
                record["expires_at"] is None
                or float(record["expires_at"]) > self.acquisition._clock()
            )
        )
        return {
            "free_only": True,
            "provider_domains": int(status["provider_count"]),
            "provider_ids": tuple(status.get("provider_ids", ())),
            "verified_gpu_capacity": verified_gpu,
            "eligible_verified_count": int(status["eligible_verified_count"]),
            "expired_verified_count": int(status["expired_verified_count"]),
        }

    def acquire_to_target(self, target: FreeComputeFleetTarget) -> dict[str, Any]:
        """Acquire every currently available eligible offer until the target is met.

        Provider limits are authoritative. A shortfall is reported as an
        evidence-backed deficit, never represented as acquired capacity.
        """
        reconciliation = self.acquisition.reconcile()
        before = self.status()
        if target.gpu_nodes <= before["verified_gpu_capacity"]:
            return {
                "target_gpu_nodes": target.gpu_nodes,
                "verified_gpu_capacity_before": before["verified_gpu_capacity"],
                "verified_gpu_capacity_after": before["verified_gpu_capacity"],
                "acquired_count": 0,
                "shortfall": 0,
                "complete": True,
                "discovery": None,
                "acquired": (),
                "errors": tuple(reconciliation["errors"]),
                "reconciled_count": len(reconciliation["reconciled"]),
            }

        discovery = self.acquisition.discover()
        acquired: list[dict[str, Any]] = []
        errors = list(reconciliation["errors"]) + list(discovery["errors"])

        # Each provider domain owns its own externally enforced capacity.
        # Acquire each distinct observed offer once. The provider and durable
        # acquisition ledger reject stale, paid, duplicate, or mismatched offers.
        for offer_data in discovery["offers"]:
            if len(acquired) + before["verified_gpu_capacity"] >= target.gpu_nodes:
                break
            try:
                from .free_compute_acquisition import FreeComputeOffer
                result = self.acquisition.acquire(FreeComputeOffer(**offer_data))
                acquired.append(asdict(result))
            except Exception as exc:
                errors.append({
                    "provider_id": str(offer_data.get("provider_id") or ""),
                    "domain_id": str(offer_data.get("domain_id") or ""),
                    "offer_id": str(offer_data.get("offer_id") or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                })

        after = self.status()
        shortfall = max(0, target.gpu_nodes - after["verified_gpu_capacity"])
        return {
            "target_gpu_nodes": target.gpu_nodes,
            "verified_gpu_capacity_before": before["verified_gpu_capacity"],
            "verified_gpu_capacity_after": after["verified_gpu_capacity"],
            "acquired_count": len(acquired),
            "shortfall": shortfall,
            "complete": shortfall == 0,
            "discovery": discovery,
            "acquired": tuple(acquired),
            "errors": tuple(errors),
            "reconciled_count": len(reconciliation["reconciled"]),
        }
