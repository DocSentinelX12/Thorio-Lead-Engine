from __future__ import annotations

import time

from lead_engine.free_compute_acquisition import (
    AcquiredCompute,
    FreeComputeAcquisitionManager,
    FreeComputeAcquisitionStore,
    FreeComputeOffer,
)


def test_external_acquisition_handoff_persists_durable_record(tmp_path):
    now = time.time()
    offer = FreeComputeOffer(
        provider_id="kaggle",
        domain_id="kaggle:test:worker",
        offer_id="offer-123",
        observed_at=now,
        expires_at=now + 3600,
        gpu_capable=True,
        no_cost=True,
        capacity_evidence={"provider": "Kaggle", "kernel_ref": "test/worker"},
    )
    acquired = AcquiredCompute(
        provider_id="kaggle",
        domain_id=offer.domain_id,
        offer_id=offer.offer_id,
        acquisition_id=FreeComputeAcquisitionStore.acquisition_id(offer),
        acquired_at=now + 1,
        expires_at=now + 1800,
        gpu_capable=True,
        enrollment={"kernel_ref": "test/worker", "external_capacity_acquired": True},
    )
    manager = FreeComputeAcquisitionManager(
        FreeComputeAcquisitionStore(str(tmp_path / "coordinator.sqlite3"))
    )

    result = manager.handoff_acquired(offer=offer, acquired=acquired)

    assert result.acquisition_id == acquired.acquisition_id
    record = manager.status()["records"][0]
    assert record["acquisition_id"] == acquired.acquisition_id
    assert record["status"] == "acquired"
    assert record["no_cost"] is True
    assert record["gpu_capable"] is True


def test_external_acquisition_handoff_is_idempotent_for_existing_acquisition(tmp_path):
    now = time.time()
    offer = FreeComputeOffer(
        provider_id="kaggle",
        domain_id="kaggle:test:worker",
        offer_id="offer-456",
        observed_at=now,
        expires_at=now + 3600,
        gpu_capable=True,
        no_cost=True,
        capacity_evidence={"provider": "Kaggle"},
    )
    acquisition_id = FreeComputeAcquisitionStore.acquisition_id(offer)
    acquired = AcquiredCompute(
        provider_id="kaggle",
        domain_id=offer.domain_id,
        offer_id=offer.offer_id,
        acquisition_id=acquisition_id,
        acquired_at=now + 1,
        expires_at=now + 1800,
        gpu_capable=True,
        enrollment={"external_capacity_acquired": True},
    )
    manager = FreeComputeAcquisitionManager(
        FreeComputeAcquisitionStore(str(tmp_path / "coordinator.sqlite3"))
    )

    manager.handoff_acquired(offer=offer, acquired=acquired)
    manager.handoff_acquired(offer=offer, acquired=acquired)

    records = manager.status()["records"]
    assert len(records) == 1
    assert records[0]["status"] == "acquired"
