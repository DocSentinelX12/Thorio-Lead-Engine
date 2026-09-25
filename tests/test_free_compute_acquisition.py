import tempfile
from pathlib import Path

import pytest

from lead_engine.free_compute_acquisition import (
    AcquiredCompute,
    FreeComputeAcquisitionError,
    FreeComputeAcquisitionManager,
    FreeComputeAcquisitionStore,
    FreeComputeOffer,
    FreeComputeProvider,
)


def offer(*, no_cost=True, expires_at=None):
    return FreeComputeOffer(
        provider_id="free-provider",
        domain_id="domain-1",
        offer_id="offer-1",
        observed_at=100.0,
        expires_at=expires_at,
        gpu_capable=True,
        no_cost=no_cost,
        capacity_evidence={"source": "provider-observation", "gpu_count": 8},
    )


class Provider(FreeComputeProvider):
    provider_id = "free-provider"

    def __init__(self):
        self.acquired = []
        self.released = []

    def discover_free(self):
        return (offer(expires_at=200.0),)

    def acquire_free(self, observed):
        acquisition_id = FreeComputeAcquisitionStore.acquisition_id(observed)
        result = AcquiredCompute(
            provider_id=observed.provider_id,
            domain_id=observed.domain_id,
            offer_id=observed.offer_id,
            acquisition_id=acquisition_id,
            acquired_at=110.0,
            expires_at=200.0,
            gpu_capable=True,
            enrollment={"worker_id": "external-worker-1", "enrollment_mode": "authenticated"},
        )
        self.acquired.append(result)
        return result

    def release_free(self, acquisition):
        self.released.append(acquisition.acquisition_id)


def test_discovery_is_durable_and_repeats_without_duplicate_records(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    manager.register(Provider())

    first = manager.discover()
    second = manager.discover()

    assert first["provider_count"] == 1
    assert len(first["offers"]) == 1
    assert len(second["offers"]) == 1
    assert len(store.records()) == 1
    assert store.records()[0]["status"] == "discovered"


def test_acquisition_is_free_only_and_returns_existing_enrollment_handoff(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    provider = Provider()
    manager = FreeComputeAcquisitionManager(store)
    manager.register(provider)

    observed = offer(expires_at=200.0)
    acquired = manager.acquire(observed)

    assert acquired.enrollment["worker_id"] == "external-worker-1"
    assert store.records()[0]["status"] == "acquired"
    assert store.records()[0]["no_cost"] is True


def test_paid_offer_is_rejected_before_provider_acquisition(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    provider = Provider()
    manager.register(provider)

    with pytest.raises(ValueError, match="no-cost"):
        manager.acquire(offer(no_cost=False))


def test_expired_offer_is_not_acquired(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 300.0)
    manager.register(Provider())

    with pytest.raises(FreeComputeAcquisitionError, match="expired"):
        manager.acquire(offer(expires_at=200.0))

    assert store.records() == []


def test_provider_failure_becomes_retry_pending_without_fabricating_capacity(tmp_path):
    class FailingProvider(Provider):
        def acquire_free(self, observed):
            raise RuntimeError("provider unavailable")

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    manager.register(FailingProvider())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        manager.acquire(offer(expires_at=200.0))

    records = store.records()
    assert len(records) == 1
    assert records[0]["status"] == "retry_pending"
    assert records[0]["gpu_capable"] is True
    assert records[0]["no_cost"] is True
    assert records[0]["enrollment"] is None


def test_release_uses_provider_and_durably_marks_release(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    provider = Provider()
    manager = FreeComputeAcquisitionManager(store)
    manager.register(provider)
    acquired = manager.acquire(offer(expires_at=200.0))

    manager.release(acquired)

    assert provider.released == [acquired.acquisition_id]
    assert store.records()[0]["status"] == "released"


def test_provider_identity_mismatch_is_rejected():
    class WrongProvider(FreeComputeProvider):
        provider_id = "free-provider"
        def discover_free(self):
            return (
                FreeComputeOffer(
                    provider_id="different-provider",
                    domain_id="domain-1",
                    offer_id="offer-1",
                    observed_at=100.0,
                    expires_at=200.0,
                    gpu_capable=True,
                    no_cost=True,
                    capacity_evidence={"source": "observed"},
                ),
            )
        def acquire_free(self, observed):
            raise AssertionError("must not acquire a mismatched offer")

    with tempfile.TemporaryDirectory() as directory:
        store = FreeComputeAcquisitionStore(str(Path(directory) / "acquisition.sqlite3"))
        manager = FreeComputeAcquisitionManager(store)
        manager.register(WrongProvider())
        result = manager.discover()
        assert result["offers"] == ()
        assert len(result["errors"]) == 1


def test_expired_verified_gpu_is_not_eligible(tmp_path):
    now = [150.0]
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: now[0])
    provider = Provider()
    manager.register(provider)

    acquired = manager.acquire(offer(expires_at=200.0))
    store.mark_worker_verified(
        acquired.acquisition_id,
        worker_id="external-worker-1",
        verification={
            "gpu_capable": True,
            "gpu_discovery_state": "healthy",
            "gpu_resources": [{"gpu_uuid": "GPU-real"}],
            "physical_fabric_evidence": {"physical_fabric": {"components": [{"component_type": "gpu", "identity": "gpu:GPU-real"}]}},
        },
    )

    assert manager.status()["eligible_verified_count"] == 1
    assert manager.status()["expired_verified_count"] == 0

    now[0] = 200.0
    status = manager.status()
    assert status["eligible_verified_count"] == 0
    assert status["expired_verified_count"] == 1
    assert status["records"][0]["status"] == "verified"
