"""Autonomous zero-cost GPU capacity broker.

This module is deliberately an acquisition controller, not another evidence
layer. It registers only provider adapters whose required credentials are
present, attempts them in priority order, and returns honest capacity status.
No paid fallback or synthetic runner/GPU state is permitted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .free_compute_acquisition import FreeComputeAcquisitionManager, FreeComputeAcquisitionStore
from .free_compute_fleet import FreeComputeFleetController, FreeComputeFleetTarget
from .kaggle_free_compute import KaggleFreeComputeProvider
from .lightning_free_compute import LightningFreeComputeProvider


@dataclass(frozen=True)
class BrokerCycle:
    target_gpu_nodes: int
    providers_registered: tuple[str, ...]
    provider_configuration_errors: tuple[dict[str, str], ...]
    result: dict[str, Any]

    @property
    def complete(self) -> bool:
        return bool(self.result.get("complete"))


class GpuCapacityBroker:
    """Continuously usable provider-neutral acquisition boundary."""

    def __init__(self, manager: FreeComputeAcquisitionManager):
        self.manager = manager
        self.fleet = FreeComputeFleetController(manager)

    @classmethod
    def from_environment(cls, db_path: str) -> tuple["GpuCapacityBroker", tuple[dict[str, str], ...]]:
        manager = FreeComputeAcquisitionManager(FreeComputeAcquisitionStore(db_path))
        errors: list[dict[str, str]] = []

        def register(name: str, factory: Callable[[], Any], enabled: bool) -> None:
            if not enabled:
                return
            try:
                manager.register(factory())
            except Exception as exc:
                errors.append({
                    "provider_id": name,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        register(
            "kaggle",
            KaggleFreeComputeProvider.from_environment,
            os.environ.get("THORIO_KAGGLE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
        )
        register(
            "lightning_ai",
            LightningFreeComputeProvider.from_environment,
            os.environ.get("THORIO_LIGHTNING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
        )
        return cls(manager), tuple(errors)

    def cycle(self, target_gpu_nodes: int) -> BrokerCycle:
        if isinstance(target_gpu_nodes, bool) or target_gpu_nodes < 0:
            raise ValueError("target_gpu_nodes must be zero or greater")
        before = self.fleet.status()
        result = self.fleet.acquire_to_target(FreeComputeFleetTarget(target_gpu_nodes))
        registered = tuple(sorted(str(item) for item in before.get("provider_ids", ())))
        return BrokerCycle(
            target_gpu_nodes=target_gpu_nodes,
            providers_registered=registered,
            provider_configuration_errors=(),
            result=result,
        )


def run_from_environment() -> dict[str, Any]:
    db_path = os.environ.get("THORIO_GPU_BROKER_DB", ".thorio/gpu-capacity.sqlite3").strip()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    target = int(os.environ.get("THORIO_GPU_TARGET_NODES", "1"))
    broker, configuration_errors = GpuCapacityBroker.from_environment(db_path)
    cycle = broker.cycle(target)
    return {
        "target_gpu_nodes": target,
        "providers_registered": cycle.providers_registered,
        "provider_configuration_errors": configuration_errors,
        "complete": cycle.complete,
        "result": cycle.result,
    }


if __name__ == "__main__":
    import json
    print("THORIO_GPU_CAPACITY_BROKER " + json.dumps(run_from_environment(), sort_keys=True, default=str))
