from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .free_compute_acquisition import (
    AcquiredCompute,
    FreeComputeAcquisitionManager,
    FreeComputeAcquisitionStore,
    FreeComputeOffer,
    FreeComputeProvider,
)
from .free_compute_fleet import FreeComputeFleetController, FreeComputeFleetError, FreeComputeFleetTarget


@dataclass
class FakeProvider(FreeComputeProvider):
    provider_id: str
    domain: str
    offer_id: str
    acquired: int = 0

    def _domain_id(self) -> str:
        return self.domain

    def discover_free(self) -> tuple[FreeComputeOffer, ...]:
        return (
            FreeComputeOffer(
                provider_id=self.provider_id,
                domain_id=self.domain,
                offer_id=self.offer_id,
                observed_at=1_700_000_000.0,
                expires_at=None,
                gpu_capable=True,
                no_cost=True,
                capacity_evidence={"provider": self.provider_id, "domain": self.domain},
            ),
        )

    def acquire_free(self, offer: FreeComputeOffer) -> AcquiredCompute:
        self.acquired += 1
        return AcquiredCompute(
            provider_id=offer.provider_id,
            domain_id=offer.domain_id,
            offer_id=offer.offer_id,
            acquisition_id=FreeComputeAcquisitionStore.acquisition_id(offer),
            acquired_at=1_700_000_001.0,
            expires_at=None,
            gpu_capable=True,
            enrollment={"external_capacity_acquired": True, "free_only": True},
        )


def _controller(tmp_path: Path) -> FreeComputeFleetController:
    manager = FreeComputeAcquisitionManager(
        FreeComputeAcquisitionStore(str(tmp_path / "fleet.sqlite3")),
        clock=lambda: 1_700_000_010.0,
    )
    manager.register(FakeProvider("kaggle", "kaggle:user-a:worker-a", "offer-a"))
    manager.register(FakeProvider("kaggle", "kaggle:user-b:worker-b", "offer-b"))
    return FreeComputeFleetController(manager)


def test_target_rejects_negative_and_bool_counts():
    for value in (-1, True):
        try:
            FreeComputeFleetTarget(value)
        except FreeComputeFleetError:
            pass
        else:
            raise AssertionError("invalid target was accepted")


def test_same_provider_can_register_multiple_independent_domains(tmp_path):
    controller = _controller(tmp_path)
    status = controller.status()
    assert status["provider_domains"] == 2
    assert status["provider_ids"] == ("kaggle",)


def test_fleet_acquires_each_observed_domain_without_inventing_verified_capacity(tmp_path):
    controller = _controller(tmp_path)

    result = controller.acquire_to_target(FreeComputeFleetTarget(gpu_nodes=2))

    assert result["acquired_count"] == 2
    assert result["verified_gpu_capacity_before"] == 0
    assert result["verified_gpu_capacity_after"] == 0
    assert result["shortfall"] == 2
    assert result["complete"] is False
    assert len(result["acquired"]) == 2


def test_fleet_does_not_acquire_when_verified_capacity_already_meets_target(tmp_path):
    controller = _controller(tmp_path)
    manager = controller.acquisition
    discovery = manager.discover()
    for offer_data in discovery["offers"]:
        offer = FreeComputeOffer(**offer_data)
        acquired = manager.acquire(offer)
        manager.confirm_worker_enrollment(
            acquisition_id=acquired.acquisition_id,
            worker_id=offer.domain_id,
            verification={
                "gpu_capable": True,
                "gpu_discovery_state": "healthy",
                "gpu_resources": [{"gpu_uuid": f"uuid-{offer.offer_id}"}],
                "physical_fabric_evidence": {"verified": True},
                "physical_gpu_execution": [{
                    "verified": True,
                    "execution_backend": "cuda",
                    "operation": "matmul",
                    "gpu_uuid": f"uuid-{offer.offer_id}",
                    "checksum": 120.0,
                    "elapsed_ms": 1.0,
                }],
            },
        )

    result = controller.acquire_to_target(FreeComputeFleetTarget(gpu_nodes=2))

    assert result["complete"] is True
    assert result["acquired_count"] == 0
    assert result["shortfall"] == 0


def test_fleet_reconciles_terminal_external_acquisition_before_targeting(tmp_path):
    @dataclass
    class LifecycleProvider(FakeProvider):
        lifecycle: str = "running"
        released: int = 0

        def acquisition_status(self, acquisition):
            return self.lifecycle

        def release_free(self, acquisition):
            self.released += 1

    manager = FreeComputeAcquisitionManager(
        FreeComputeAcquisitionStore(str(tmp_path / "fleet-reconcile.sqlite3")),
        clock=lambda: 1_700_000_010.0,
    )
    provider = LifecycleProvider("kaggle", "kaggle:user-a:worker-a", "offer-a")
    manager.register(provider)
    controller = FreeComputeFleetController(manager)

    first = manager.acquire(provider.discover_free()[0])
    assert manager.status()["acquired_unverified_count"] == 1

    provider.lifecycle = "complete"
    result = controller.acquire_to_target(FreeComputeFleetTarget(gpu_nodes=1))

    assert result["reconciled_count"] == 1
    assert result["acquired_count"] == 1
    assert provider.released == 1
    assert manager.status()["records"][0]["status"] == "acquired"
    assert first.acquisition_id == manager.status()["records"][0]["acquisition_id"]
