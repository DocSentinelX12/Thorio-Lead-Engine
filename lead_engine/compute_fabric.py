"""Hierarchical compute-fabric orchestration above provider adapters and scheduling.

This layer coordinates provider observation, inventory truth, capability scheduling,
and resource lifecycle without becoming a second business queue. Provider adapters
remain responsible for authoritative external observation; ComputeInventory remains
the durable physical resource record; ComputeScheduler remains the placement policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Mapping

from .compute_inventory import ComputeInventory
from .compute_provider import ComputeProvider, ProviderResourceSnapshot
from .compute_resources import ComputeRequirements
from .compute_scheduler import ComputeAllocation, ComputeScheduler, ComputeSchedulingError


@dataclass(frozen=True)
class ProviderObservation:
    provider_id: str
    domain_id: str
    state: str
    observed_at: float | None
    observed_nodes: int
    observed_gpus: int
    ephemeral: bool
    expires_at: float | None
    error: str | None = None


@dataclass(frozen=True)
class FabricCycleReport:
    observed: tuple[ProviderObservation, ...]
    eligible_resources: int
    scheduled_allocations: int
    reconciled_attempts: int = 0
    requeued_tasks: int = 0


@dataclass(frozen=True)
class FabricControllerCycle:
    refresh: FabricCycleReport
    recovered_expired_tasks: int
    reconciled_attempts: int
    requeued_tasks: int
    scheduled_allocations: tuple[dict[str, Any], ...]


class ComputeProviderRegistry:
    """Deterministic registry for authorized provider adapters."""

    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], ComputeProvider] = {}

    def register(self, provider: ComputeProvider, *, domain_id: str) -> None:
        provider_id = str(provider.provider_id).strip()
        domain = str(domain_id).strip()
        if not provider_id or not domain:
            raise ValueError("provider_id and domain_id are required")
        key = (provider_id, domain)
        if key in self._providers:
            raise ValueError(f"provider already registered: {provider_id}/{domain}")
        self._providers[key] = provider

    def unregister(self, provider_id: str, domain_id: str) -> bool:
        return self._providers.pop((str(provider_id).strip(), str(domain_id).strip()), None) is not None

    def providers(self) -> tuple[ComputeProvider, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))

    def entries(self) -> tuple[tuple[str, str, ComputeProvider], ...]:
        return tuple((provider_id, domain_id, self._providers[(provider_id, domain_id)]) for provider_id, domain_id in sorted(self._providers))

    def provider(self, provider_id: str, domain_id: str) -> ComputeProvider | None:
        return self._providers.get((str(provider_id).strip(), str(domain_id).strip()))


class ComputeFabricOrchestrator:
    """Run one evidence-driven control-plane cycle over the physical fabric.

    The orchestrator never creates business work, removes durable work, or
    treats an adapter failure as proof of successful capacity. It only connects
    provider observation, inventory, and scheduling into one repeatable loop.
    """

    def __init__(
        self,
        inventory: ComputeInventory,
        *,
        registry: ComputeProviderRegistry | None = None,
        scheduler: ComputeScheduler | None = None,
        clock=time,
    ) -> None:
        self.inventory = inventory
        self.registry = registry or ComputeProviderRegistry()
        self.scheduler = scheduler or ComputeScheduler(inventory)
        self._clock = clock

    @staticmethod
    def _observation_from_snapshot(snapshot: ProviderResourceSnapshot) -> ProviderObservation:
        return ProviderObservation(
            provider_id=snapshot.provider_id,
            domain_id=snapshot.domain_id,
            state="ephemeral" if snapshot.ephemeral else "observed",
            observed_at=snapshot.observed_at,
            observed_nodes=len(snapshot.nodes),
            observed_gpus=sum(node.gpu_count for node in snapshot.nodes),
            ephemeral=snapshot.ephemeral,
            expires_at=snapshot.expires_at,
        )

    def observe_provider(self, provider: ComputeProvider, *, domain_id: str) -> ProviderObservation:
        """Discover one provider and atomically publish its normalized snapshot."""
        snapshot = provider.discover()
        if snapshot.provider_id != provider.provider_id:
            raise ValueError(
                f"provider identity mismatch: adapter={provider.provider_id!r} "
                f"snapshot={snapshot.provider_id!r}"
            )
        if snapshot.domain_id != domain_id:
            raise ValueError(
                f"provider domain mismatch: adapter={domain_id!r} "
                f"snapshot={snapshot.domain_id!r}"
            )
        now = self._clock()
        if snapshot.expires_at is not None and snapshot.expires_at <= now:
            raise ValueError("provider snapshot is already expired")
        self.inventory.observe(snapshot)
        return self._observation_from_snapshot(snapshot)

    def refresh(self) -> FabricCycleReport:
        """Observe every registered provider and return evidence-backed capacity."""
        observations: list[ProviderObservation] = []
        for provider_id, domain, provider in self.registry.entries():
            try:
                observations.append(self.observe_provider(provider, domain_id=domain))
            except Exception as exc:
                health = provider.health()
                health_state = str(health.get("state", "unknown")).strip().lower()
                if health_state in {"missing", "offline", "unavailable"}:
                    self.inventory.mark_provider_missing(
                        provider.provider_id, domain, observed_at=self._clock()
                    )
                observations.append(
                    ProviderObservation(
                        provider_id=provider.provider_id,
                        domain_id=domain,
                        state="action_required" if health_state not in {"missing", "offline", "unavailable"} else "unavailable",
                        observed_at=None,
                        observed_nodes=0,
                        observed_gpus=0,
                        ephemeral=False,
                        expires_at=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return FabricCycleReport(
            observed=tuple(observations),
            eligible_resources=len(self.inventory.eligible(now=self._clock())),
            scheduled_allocations=0,
        )

    def allocate(self, requirements: ComputeRequirements, *, allocation_id: str) -> ComputeAllocation:
        """Select and reserve physical resources using the existing scheduler."""
        return self.scheduler.allocate(requirements, allocation_id)

    def release(self, resource_keys: list[str] | tuple[str, ...]) -> int:
        """Return physical resources through the existing inventory-backed scheduler."""
        return self.scheduler.release(resource_keys)

    def health(self) -> Mapping[str, Any]:
        """Expose control-plane fabric state without inventing capacity."""
        resources = self.inventory.eligible(now=self._clock())
        by_provider: dict[str, int] = {}
        for resource in resources:
            provider_id = str(resource["provider_id"])
            by_provider[provider_id] = by_provider.get(provider_id, 0) + 1
        return {
            "state": "healthy" if resources else "awaiting_resource",
            "registered_providers": len(self.registry.providers()),
            "eligible_resources": len(resources),
            "eligible_resources_by_provider": dict(sorted(by_provider.items())),
        }

    def close(self) -> None:
        for provider in self.registry.providers():
            provider.close()


class ComputeFabricController:
    """Continuously drive the durable compute queue through the fabric.

    This controller composes provider observation, recovery, reconciliation,
    and physical scheduling. The per-cycle allocation count is a batch size,
    not a global backlog cap.
    """

    def __init__(self, coordinator: Any, *, fabric: ComputeFabricOrchestrator | None = None, clock=time, sleeper=None) -> None:
        self.coordinator = coordinator
        self.fabric = fabric or coordinator.compute_fabric
        self._clock = clock
        self._sleep = sleeper or __import__("time").sleep

    def cycle(self, *, max_allocations_per_cycle: int = 50) -> FabricControllerCycle:
        if max_allocations_per_cycle < 1:
            raise ValueError("max_allocations_per_cycle must be positive")
        recovered = int(self.coordinator.recover_expired_tasks())
        reconciliation = self.coordinator.reconcile_fabric()
        refresh = self.fabric.refresh()
        scheduled: list[dict[str, Any]] = []
        for _ in range(max_allocations_per_cycle):
            assignment = self.coordinator.claim_physical()
            if assignment is None:
                break
            scheduled.append({
                "task_id": str(assignment["task_id"]),
                "attempt_id": str(assignment["attempt_id"]),
                "generation": int(assignment["generation"]),
                "execution_identity": str(assignment["execution_identity"]),
                "physical_allocation": assignment["physical_allocation"],
            })
        reconciled = int(reconciliation.get("reconciled", 0))
        requeued = int(reconciliation.get("requeued", 0))
        cycle_report = FabricCycleReport(
            observed=refresh.observed,
            eligible_resources=len(self.fabric.inventory.eligible(now=self._clock())),
            scheduled_allocations=len(scheduled),
            reconciled_attempts=reconciled,
            requeued_tasks=requeued,
        )
        return FabricControllerCycle(
            refresh=cycle_report,
            recovered_expired_tasks=recovered,
            reconciled_attempts=reconciled,
            requeued_tasks=requeued,
            scheduled_allocations=tuple(scheduled),
        )

    def run_forever(self, *, interval_seconds: float = 5.0, max_allocations_per_cycle: int = 50, stop_event: Any | None = None) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must not be negative")
        if max_allocations_per_cycle < 1:
            raise ValueError("max_allocations_per_cycle must be positive")
        while stop_event is None or not stop_event.is_set():
            self.cycle(max_allocations_per_cycle=max_allocations_per_cycle)
            if stop_event is None:
                self._sleep(interval_seconds)
            else:
                stop_event.wait(interval_seconds)
