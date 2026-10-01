from __future__ import annotations

import json

import pytest

from lead_engine.free_compute_acquisition import FreeComputeAcquisitionManager, FreeComputeAcquisitionStore
from lead_engine.lightning_free_compute import (
    LightningFreeComputeConfig,
    LightningFreeComputeError,
    LightningFreeComputeProvider,
)


def _config(**overrides):
    values = {
        "studio_name": "thorio-gpu-test",
        "machine": "T4",
        "teamspace": "default",
        "repo": "https://github.com/DocSentinelX12/Thorio-Lead-Engine.git",
        "ref": "feature/gpu-fabric-foundation",
        "free_hours_remaining": 2.0,
        "offer_ttl_seconds": 1200,
    }
    values.update(overrides)
    return LightningFreeComputeConfig(**values)


def test_lightning_provider_is_strictly_zero_cost():
    provider = LightningFreeComputeProvider(_config())
    offer = provider.discover_free()[0]
    assert offer.provider_id == "lightning_ai"
    assert offer.no_cost is True
    assert offer.gpu_capable is True
    assert offer.capacity_evidence["free_only_enforcement"] == "no_purchase_no_upgrade_no_paid_fallback"


def test_lightning_provider_refuses_unattested_free_budget():
    provider = LightningFreeComputeProvider(_config(free_hours_remaining=None))
    with pytest.raises(LightningFreeComputeError, match="free GPU budget is not attested"):
        provider.discover_free()


def test_lightning_provider_registers_through_existing_acquisition_boundary(tmp_path):
    manager = FreeComputeAcquisitionManager(FreeComputeAcquisitionStore(str(tmp_path / "acq.sqlite3")))
    provider = LightningFreeComputeProvider(_config())
    manager.register(provider)
    status = manager.status()
    assert status["provider_ids"] == ("lightning_ai",)
    discovery = manager.discover()
    assert discovery["provider_ids"] == ("lightning_ai",)
    assert len(discovery["offers"]) == 1


def test_lightning_domain_identity_is_stable_and_provider_scoped():
    first = LightningFreeComputeProvider(_config())._domain_id()
    second = LightningFreeComputeProvider(_config())._domain_id()
    assert first == second == "lightning_ai:default:thorio-gpu-test"


def test_lightning_bootstrap_evidence_requires_physical_cuda_execution():
    valid = {
        "gpu_discovery_state": "healthy",
        "physical_gpu_execution": [{"verified": True, "execution_backend": "cuda", "gpu_uuid": "GPU-1"}],
    }
    assert LightningFreeComputeProvider._parse_bootstrap_evidence(
        "THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps(valid)
    ) == valid
    with pytest.raises(LightningFreeComputeError, match="physical CUDA execution"):
        LightningFreeComputeProvider._parse_bootstrap_evidence(
            "THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps({"gpu_discovery_state": "healthy"})
        )


def test_lightning_bootstrap_command_contains_exact_branch_and_acquisition_identity():
    provider = LightningFreeComputeProvider(_config())
    command = provider._bootstrap_command("acq-123")
    assert "--branch feature/gpu-fabric-foundation" in command
    assert "--acquisition-id acq-123" in command
    assert "lead_engine.lightning_worker_bootstrap" in command
