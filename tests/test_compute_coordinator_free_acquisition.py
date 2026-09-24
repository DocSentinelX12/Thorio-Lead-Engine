import time

from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.free_compute_acquisition import AcquiredCompute, FreeComputeOffer, FreeComputeProvider, FreeComputeAcquisitionStore


class CoordinatorProvider(FreeComputeProvider):
    provider_id = "free-provider"

    def discover_free(self):
        return (
            FreeComputeOffer(
                provider_id=self.provider_id,
                domain_id="domain-1",
                offer_id="offer-1",
                observed_at=time.time(),
                expires_at=time.time() + 300,
                gpu_capable=True,
                no_cost=True,
                capacity_evidence={"source": "external-provider", "gpu_count": 8},
            ),
        )

    def acquire_free(self, offer):
        return AcquiredCompute(
            provider_id=offer.provider_id,
            domain_id=offer.domain_id,
            offer_id=offer.offer_id,
            acquisition_id=FreeComputeAcquisitionStore.acquisition_id(offer),
            acquired_at=time.time(),
            expires_at=offer.expires_at,
            gpu_capable=offer.gpu_capable,
            enrollment={"worker_id": "external-worker", "enrollment_mode": "authenticated"},
        )


def test_coordinator_exposes_zero_cost_acquisition_without_bypassing_fabric_inventory(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="token")
    coordinator.register_free_compute_provider(CoordinatorProvider())

    discovered = coordinator.discover_free_compute()
    assert len(discovered["offers"]) == 1
    assert coordinator.free_compute_status()["eligible_acquired_count"] == 0

    acquired = coordinator.acquire_free_compute(
        FreeComputeOffer(
            provider_id="free-provider",
            domain_id="domain-1",
            offer_id="offer-1",
            observed_at=100.0,
            expires_at=200.0,
            gpu_capable=True,
            no_cost=True,
            capacity_evidence={"source": "external-provider", "gpu_count": 8},
        )
    )

    assert acquired.enrollment["worker_id"] == "external-worker"
    status = coordinator.free_compute_status()
    assert status["free_only"] is True
    assert status["paid_capacity_allowed"] is False
    assert status["eligible_acquired_count"] == 1
    assert coordinator.inventory.resources() == []
