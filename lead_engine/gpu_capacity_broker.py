"""Autonomous zero-cost GPU capacity broker.

This module is deliberately an acquisition controller, not another evidence
layer. It registers only provider adapters whose required credentials and
coordinator enrollment inputs are present, attempts them in priority order, and
returns honest capacity status. No paid fallback or synthetic runner/GPU state
is permitted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .free_compute_acquisition import FreeComputeAcquisitionManager, FreeComputeAcquisitionStore
from .free_compute_fleet import FreeComputeFleetController, FreeComputeFleetTarget
from .kaggle_free_compute import KaggleFreeComputeProvider


@dataclass(frozen=True)
class BrokerCycle:
    target_gpu_nodes: int
    providers_registered: tuple[str, ...]
    provider_configuration_errors: tuple[dict[str, str], ...]
    result: dict[str, Any]

    @property
    def complete(self) -> bool:
        return bool(self.result.get("complete"))


def _enabled(name: str) -> bool:
    return os.environ.get(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _missing_environment(*names: str) -> tuple[str, ...]:
    return tuple(name for name in names if not os.environ.get(name, "").strip())


def provider_readiness_from_environment() -> dict[str, dict[str, Any]]:
    """Return deterministic readiness for each configured free provider.

    Readiness is intentionally stricter than adapter construction. A provider
    is not registered merely because one constructor argument exists. The
    acquisition path must have credentials to reach the provider and the
    coordinator enrollment credentials required to turn acquired capacity into
    an authenticated worker.
    """
    coordinator_missing = _missing_environment(
        "THORIO_COMPUTE_COORDINATOR_URL",
        "THORIO_COMPUTE_AUTH_TOKEN",
    )

    kaggle_enabled = _enabled("THORIO_KAGGLE_ENABLED")
    kaggle_missing = ()
    if kaggle_enabled:
        missing = list(_missing_environment("THORIO_KAGGLE_USERNAME", "KAGGLE_API_TOKEN", "THORIO_KAGGLE_SECRET_DATASET_SLUG"))
        missing.extend(coordinator_missing)
        kaggle_missing = tuple(dict.fromkeys(missing))

    return {
        "kaggle": {
            "enabled": kaggle_enabled,
            "ready": kaggle_enabled and not kaggle_missing,
            "missing": kaggle_missing,
        },
    }


class GpuCapacityBroker:
    """Continuously usable provider-neutral acquisition boundary."""

    def __init__(self, manager: FreeComputeAcquisitionManager):
        self.manager = manager
        self.fleet = FreeComputeFleetController(manager)

    @classmethod
    def from_environment(cls, db_path: str) -> tuple["GpuCapacityBroker", tuple[dict[str, str], ...]]:
        manager = FreeComputeAcquisitionManager(FreeComputeAcquisitionStore(db_path))
        errors: list[dict[str, str]] = []
        readiness = provider_readiness_from_environment()

        def register(name: str, factory: Callable[[], Any]) -> None:
            state = readiness[name]
            if not state["enabled"]:
                return
            if not state["ready"]:
                errors.append({
                    "provider_id": name,
                    "error": "provider skipped because required environment is missing",
                    "missing": ",".join(state["missing"]),
                })
                return
            try:
                manager.register(factory())
            except Exception as exc:
                errors.append({
                    "provider_id": name,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        register("kaggle", KaggleFreeComputeProvider.from_environment)
        return cls(manager), tuple(errors)

    def cycle(self, target_gpu_nodes: int, configuration_errors: tuple[dict[str, str], ...] = ()) -> BrokerCycle:
        if isinstance(target_gpu_nodes, bool) or target_gpu_nodes < 0:
            raise ValueError("target_gpu_nodes must be zero or greater")
        before = self.fleet.status()
        result = self.fleet.acquire_to_target(FreeComputeFleetTarget(target_gpu_nodes))
        registered = tuple(sorted(str(item) for item in before.get("provider_ids", ())))
        return BrokerCycle(
            target_gpu_nodes=target_gpu_nodes,
            providers_registered=registered,
            provider_configuration_errors=configuration_errors,
            result=result,
        )


def run_from_environment() -> dict[str, Any]:
    db_path = os.environ.get("THORIO_GPU_BROKER_DB", ".thorio/gpu-capacity.sqlite3").strip()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    target = int(os.environ.get("THORIO_GPU_TARGET_NODES", "1"))
    broker, configuration_errors = GpuCapacityBroker.from_environment(db_path)
    cycle = broker.cycle(target, configuration_errors)
    return {
        "target_gpu_nodes": target,
        "providers_registered": cycle.providers_registered,
        "provider_configuration_errors": cycle.provider_configuration_errors,
        "complete": cycle.complete,
        "result": cycle.result,
    }


if __name__ == "__main__":
    import json
    print("THORIO_GPU_CAPACITY_BROKER " + json.dumps(run_from_environment(), sort_keys=True, default=str))
