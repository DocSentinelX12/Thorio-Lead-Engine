import subprocess
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
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    manager.register(provider)

    observed = offer(expires_at=200.0)
    acquired = manager.acquire(observed)

    assert acquired.enrollment["worker_id"] == "external-worker-1"
    assert store.records()[0]["status"] == "acquired"
    assert store.records()[0]["no_cost"] is True


def test_acquisition_cannot_extend_observed_offer_lifetime(tmp_path):
    class ExtendingProvider(Provider):
        def acquire_free(self, observed):
            acquisition_id = FreeComputeAcquisitionStore.acquisition_id(observed)
            return AcquiredCompute(
                provider_id=observed.provider_id,
                domain_id=observed.domain_id,
                offer_id=observed.offer_id,
                acquisition_id=acquisition_id,
                acquired_at=110.0,
                expires_at=250.0,
                gpu_capable=True,
                enrollment={"worker_id": "external-worker-1"},
            )

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    manager.register(ExtendingProvider())

    with pytest.raises(FreeComputeAcquisitionError, match="expiry cannot extend"):
        manager.acquire(offer(expires_at=200.0))

    assert store.records()[0]["status"] == "retry_pending"


def test_acquisition_cannot_drop_a_finite_offer_expiry(tmp_path):
    class UnboundedProvider(Provider):
        def acquire_free(self, observed):
            acquisition_id = FreeComputeAcquisitionStore.acquisition_id(observed)
            return AcquiredCompute(
                provider_id=observed.provider_id,
                domain_id=observed.domain_id,
                offer_id=observed.offer_id,
                acquisition_id=acquisition_id,
                acquired_at=110.0,
                expires_at=None,
                gpu_capable=True,
                enrollment={"worker_id": "external-worker-1"},
            )

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    manager.register(UnboundedProvider())

    with pytest.raises(FreeComputeAcquisitionError, match="expiry cannot extend"):
        manager.acquire(offer(expires_at=200.0))

    assert store.records()[0]["status"] == "retry_pending"


def test_acquisition_cannot_claim_gpu_capability_absent_from_offer(tmp_path):
    class GpuClaimingProvider(Provider):
        def acquire_free(self, observed):
            acquisition_id = FreeComputeAcquisitionStore.acquisition_id(observed)
            return AcquiredCompute(
                provider_id=observed.provider_id,
                domain_id=observed.domain_id,
                offer_id=observed.offer_id,
                acquisition_id=acquisition_id,
                acquired_at=110.0,
                expires_at=200.0,
                gpu_capable=True,
                enrollment={"worker_id": "external-worker-1"},
            )

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    manager.register(GpuClaimingProvider())

    cpu_offer = FreeComputeOffer(
        provider_id="free-provider",
        domain_id="domain-1",
        offer_id="offer-cpu",
        observed_at=100.0,
        expires_at=200.0,
        gpu_capable=False,
        no_cost=True,
        capacity_evidence={"source": "provider-observation", "gpu_count": 0},
    )

    with pytest.raises(FreeComputeAcquisitionError, match="GPU capability"):
        manager.acquire(cpu_offer)

    assert store.records()[0]["status"] == "retry_pending"


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
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
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
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
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
            "physical_gpu_execution": [{
                "verified": True,
                "execution_backend": "cuda",
                "operation": "torch_cuda_matmul",
                "gpu_uuid": "GPU-real",
                "checksum": 120.0,
                "elapsed_ms": 1.0,
            }],
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


def test_continuous_hunter_discovers_and_acquires_without_stopping_on_provider_failure(tmp_path):
    class FlakyProvider(Provider):
        provider_id = "flaky-provider"

        def __init__(self):
            super().__init__()
            self.discovery_calls = 0

        def discover_free(self):
            self.discovery_calls += 1
            if self.discovery_calls == 1:
                raise RuntimeError("temporarily unavailable")
            return (
                FreeComputeOffer(
                    provider_id=self.provider_id,
                    domain_id="domain-1",
                    offer_id="offer-flaky",
                    observed_at=100.0,
                    expires_at=500.0,
                    gpu_capable=True,
                    no_cost=True,
                    capacity_evidence={"source": "provider-observation", "gpu_count": 8},
                ),
            )

        def acquire_free(self, observed):
            acquisition_id = FreeComputeAcquisitionStore.acquisition_id(observed)
            return AcquiredCompute(
                provider_id=observed.provider_id,
                domain_id=observed.domain_id,
                offer_id=observed.offer_id,
                acquisition_id=acquisition_id,
                acquired_at=110.0,
                expires_at=500.0,
                gpu_capable=True,
                enrollment={"worker_id": "flaky-worker", "enrollment_mode": "authenticated"},
            )

    class HealthyProvider(Provider):
        provider_id = "healthy-provider"

        def discover_free(self):
            return (
                FreeComputeOffer(
                    provider_id=self.provider_id,
                    domain_id="domain-1",
                    offer_id="offer-healthy",
                    observed_at=100.0,
                    expires_at=500.0,
                    gpu_capable=True,
                    no_cost=True,
                    capacity_evidence={"source": "provider-observation", "gpu_count": 4},
                ),
            )

        def acquire_free(self, observed):
            acquisition_id = FreeComputeAcquisitionStore.acquisition_id(observed)
            return AcquiredCompute(
                provider_id=observed.provider_id,
                domain_id=observed.domain_id,
                offer_id=observed.offer_id,
                acquisition_id=acquisition_id,
                acquired_at=110.0,
                expires_at=500.0,
                gpu_capable=True,
                enrollment={"worker_id": "healthy-worker", "enrollment_mode": "authenticated"},
            )

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    flaky = FlakyProvider()
    manager.register(flaky)
    manager.register(HealthyProvider())

    first = manager.hunt_once()
    assert first["provider_count"] == 2
    assert first["acquired_count"] == 1
    assert len(first["errors"]) == 1
    assert first["errors"][0]["provider_id"] == "flaky-provider"

    second = manager.hunt_once()
    assert second["acquired_count"] == 1
    records = {item["provider_id"]: item for item in store.records()}
    assert records["flaky-provider"]["status"] == "acquired"
    assert records["healthy-provider"]["status"] == "acquired"
    assert flaky.discovery_calls == 2


def test_continuous_hunter_runs_immediately_then_waits_between_cycles(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    provider = Provider()
    manager.register(provider)

    sleeps = []
    cycles = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise StopIteration

    with pytest.raises(StopIteration):
        manager.run_continuously(interval_seconds=7.0, sleep=sleep, on_cycle=lambda result: cycles.append(result))

    assert len(cycles) == 2
    assert sleeps == [7.0, 7.0]


def test_gpu_worker_verification_rejects_missing_physical_execution_evidence(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    provider = Provider()
    manager.register(provider)
    acquired = manager.acquire(offer(expires_at=200.0))

    with pytest.raises(FreeComputeAcquisitionError, match="physical CUDA execution evidence"):
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

    assert store.records()[0]["status"] == "acquired"


def test_hunt_reconciles_terminal_external_acquisition_and_allows_reacquisition(tmp_path):
    class LifecycleProvider(Provider):
        def __init__(self):
            super().__init__()
            self.lifecycle = "running"

        def acquisition_status(self, acquisition):
            return self.lifecycle

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    provider = LifecycleProvider()
    manager = FreeComputeAcquisitionManager(store, clock=lambda: 150.0)
    manager.register(provider)

    first = manager.hunt_once()
    assert first["acquired_count"] == 1
    assert first["reconciled_count"] == 0
    assert store.records()[0]["status"] == "acquired"

    provider.lifecycle = "complete"
    second = manager.hunt_once()

    assert second["reconciled_count"] == 1
    assert second["acquired_count"] == 1
    assert provider.released == [provider.acquired[0].acquisition_id]
    assert store.records()[0]["status"] == "acquired"


def test_provider_capabilities_are_conservative_by_default(tmp_path):
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    manager.register(Provider())

    capabilities = manager.provider_capabilities()
    assert capabilities["free-provider"]["zero_cost_acquisition"] is True
    assert capabilities["free-provider"]["gpu_acquisition"] is False
    assert capabilities["free-provider"]["github_jit_runner"] is False
    assert capabilities["free-provider"]["networked_multi_node"] is False


def test_provider_capabilities_are_not_physical_gpu_proof(tmp_path):
    class DeclaringProvider(Provider):
        def capabilities(self):
            from lead_engine.compute_fabric import ProviderCapabilities
            return ProviderCapabilities(
                gpu_acquisition=True,
                cuda_execution=True,
                ephemeral_runner=True,
                github_jit_runner=True,
            )

    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    manager.register(DeclaringProvider())

    capabilities = manager.provider_capabilities()["free-provider"]
    assert capabilities["gpu_acquisition"] is True
    assert capabilities["cuda_execution"] is True
    assert store.records() == []


def test_kaggle_wait_for_running_tolerates_initial_not_found_visibility_race():
    from lead_engine.kaggle_free_compute import KaggleFreeComputeConfig, KaggleFreeComputeProvider

    statuses = iter(["not_found", "not_found", "queued", "running"])
    sleeps = []

    class ProviderWithDelayedVisibility(KaggleFreeComputeProvider):
        def _kernel_status(self, kernel_ref):
            return next(statuses)

        def _kernel_list_snapshot(self, kernel_ref):
            return False, None

    provider = ProviderWithDelayedVisibility(
        KaggleFreeComputeConfig(
            username="test-user",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
            acquisition_ready_timeout_seconds=20,
            acquisition_ready_poll_interval_seconds=1,
        ),
        runner=lambda *args, **kwargs: None,
        clock=lambda: 100.0,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    assert provider._wait_for_running("test-user/test-kernel") == "running"
    assert sleeps == [1, 1, 1]



def test_kaggle_acquisition_publishes_kernel_for_api_status_visibility():
    import json

    from lead_engine.kaggle_free_compute import KaggleFreeComputeConfig, KaggleFreeComputeProvider

    captured = {}

    def runner(command, *, timeout, cwd=None):
        if command[1:3] == ["kernels", "push"]:
            metadata_path = command[command.index("-p") + 1] + "/kernel-metadata.json"
            captured["metadata"] = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(command, 0, "Kernel version 1 successfully pushed.", "")
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="test-user",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
            acquisition_ready_timeout_seconds=1,
        ),
        runner=runner,
        clock=lambda: 100.0,
        sleeper=lambda seconds: None,
    )
    quota = {
        "resource": "GPU",
        "remaining_hours": 6.0,
        "total_hours": 30.0,
        "used_hours": 24.0,
        "refresh_at": "",
    }
    provider._quota = lambda: quota
    statuses = iter(["not_found", "not_found", "running"])
    provider._kernel_status = lambda kernel_ref: next(statuses)
    provider._runner_bootstrap_script = lambda: "echo runner"
    offer = provider.discover_free()[0]

    provider.acquire_free(offer)

    assert captured["metadata"]["is_private"] is False


def test_kaggle_provider_declares_runner_and_gpu_capabilities_without_nccL_claim():
    from lead_engine.kaggle_free_compute import KaggleFreeComputeConfig, KaggleFreeComputeProvider

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(username="test-user", github_runner_jit_token_dataset_slug="thorio-runner-credentials-test"),
        runner=lambda *args, **kwargs: None,
    )

    capabilities = provider.capabilities().to_dict()
    assert capabilities["zero_cost_acquisition"] is True
    assert capabilities["gpu_acquisition"] is True
    assert capabilities["cuda_execution"] is True
    assert capabilities["ephemeral_runner"] is True
    assert capabilities["github_jit_runner"] is True
    assert capabilities["nccl_execution"] is False
    assert capabilities["multi_node"] is False



def test_provider_capabilities_require_declared_capabilities():
    from lead_engine.compute_fabric import ProviderCapabilities

    capabilities = ProviderCapabilities(
        gpu_acquisition=True,
        cuda_execution=True,
        api_gpu_execution=True,
    )
    assert capabilities.missing({"gpu_acquisition": True, "cuda_execution": True}) == ()
    assert capabilities.missing({"networked_multi_node": True}) == ("networked_multi_node",)


def test_provider_capabilities_reject_unknown_requirement():
    from lead_engine.compute_fabric import ProviderCapabilities

    with pytest.raises(ValueError, match="unknown provider capability"):
        ProviderCapabilities().missing({"not_a_capability": True})


def test_acquire_for_requirements_filters_providers_before_acquisition(tmp_path):
    from lead_engine.free_compute_acquisition import FreeComputeAcquisitionManager, FreeComputeAcquisitionStore

    class Provider:
        def __init__(self, provider_id, capabilities):
            self.provider_id = provider_id
            self._capabilities = capabilities
            self.acquired = 0

        def capabilities(self):
            from lead_engine.compute_fabric import ProviderCapabilities
            return ProviderCapabilities(**self._capabilities)

        def discover_free(self):
            from lead_engine.free_compute_acquisition import FreeComputeOffer
            import time
            return (FreeComputeOffer(
                provider_id=self.provider_id,
                domain_id=self.provider_id,
                offer_id="offer",
                observed_at=time.time(),
                expires_at=time.time() + 300,
                gpu_capable=True,
                no_cost=True,
                capacity_evidence={"provider": self.provider_id},
            ),)

        def acquire_free(self, offer):
            self.acquired += 1
            from lead_engine.free_compute_acquisition import AcquiredCompute
            return AcquiredCompute(
                provider_id=offer.provider_id,
                domain_id=offer.domain_id,
                offer_id=offer.offer_id,
                acquisition_id=FreeComputeAcquisitionStore.acquisition_id(offer),
                acquired_at=offer.observed_at + 0.001,
                expires_at=offer.expires_at,
                gpu_capable=True,
                enrollment={"worker_id": self.provider_id},
            )

    rejected = Provider("isolated", {"gpu_acquisition": True, "cuda_execution": True})
    selected = Provider("cluster", {
        "gpu_acquisition": True,
        "cuda_execution": True,
        "networked_multi_node": True,
    })
    manager = FreeComputeAcquisitionManager(FreeComputeAcquisitionStore(str(tmp_path / "compute.sqlite3")))
    manager.register(rejected)
    manager.register(selected)

    result = manager.acquire_for_requirements(
        required_capabilities={"gpu_acquisition": True, "cuda_execution": True, "networked_multi_node": True},
        gpu_required=True,
    )

    assert result["status"] == "acquired"
    assert result["acquired"]["provider_id"] == "cluster"
    assert rejected.acquired == 0
    assert selected.acquired == 1
