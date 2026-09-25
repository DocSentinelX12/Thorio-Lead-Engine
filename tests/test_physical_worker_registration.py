from __future__ import annotations

from pathlib import Path

from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_pool import ComputePool, WorkerIdentity, local_worker_identity
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.free_compute_acquisition import AcquiredCompute, FreeComputeAcquisitionStore, FreeComputeOffer, FreeComputeProvider
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


def _identity(*, worker_id: str = "node-a") -> WorkerIdentity:
    gpu = GpuResource(
        node_id=worker_id,
        gpu_id="0",
        gpu_uuid="GPU-0",
        vram_bytes=80 * 1024**3,
        pci_bus_id="0000:3b:00.0",
        numa_node=0,
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    return WorkerIdentity(
        worker_id=worker_id,
        hostname="host-a",
        architecture="x86_64",
        cpu_count=64,
        memory_mb=524288,
        capabilities=("lead-processing",),
        gpu_resources=(gpu,),
        driver_version="550.54.15",
        cuda_version="12.4",
        domain_id="supercomputer-a",
        physical_fabric_evidence={
            "physical_fabric": {
                "components": [
                    {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": worker_id},
                    {"component_type": "pci", "identity": "pci:0000:3b:00.0", "node_id": worker_id},
                    {"component_type": "numa", "identity": "numa:0", "node_id": worker_id},
                    {"component_type": "nic", "identity": "nic:eth0", "node_id": worker_id},
                    {"component_type": "rdma_device", "identity": "rdma:mlx5_0", "node_id": worker_id},
                    {"component_type": "rdma_port", "identity": "rdma:mlx5_0:1", "node_id": worker_id},
                ],
                "relationships": [
                    {"relationship_type": "gpu_to_pci", "source": "gpu:GPU-0", "target": "pci:0000:3b:00.0"},
                    {"relationship_type": "gpu_to_numa", "source": "gpu:GPU-0", "target": "numa:0"},
                    {"relationship_type": "gpu_to_nic", "source": "gpu:GPU-0", "target": "nic:eth0"},
                    {"relationship_type": "nic_to_rdma_device", "source": "nic:eth0", "target": "rdma:mlx5_0"},
                    {"relationship_type": "rdma_device_to_port", "source": "rdma:mlx5_0", "target": "rdma:mlx5_0:1"},
                ],
            }
        },
    )


def test_worker_registration_persists_domain_and_physical_evidence(tmp_path: Path) -> None:
    pool = ComputePool(str(tmp_path / "pool.sqlite3"))
    result = pool.register(_identity())
    assert result["domain_id"] == "supercomputer-a"
    assert result["physical_fabric_evidence"]["physical_fabric"]["components"]
    stored = pool.worker("node-a")
    assert stored["domain_id"] == "supercomputer-a"
    assert stored["physical_fabric_evidence"]["physical_fabric"]["relationships"]


def test_coordinator_registration_publishes_worker_physical_inventory(tmp_path: Path) -> None:
    inventory_path = str(tmp_path / "inventory.sqlite3")
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        inventory=__import__("lead_engine.compute_inventory", fromlist=["ComputeInventory"]).ComputeInventory(inventory_path),
    )
    coordinator.register_worker(_identity())

    records = coordinator.inventory.physical_component_observations()
    assert {record["identity"] for record in records} == {
        "gpu:GPU-0",
        "pci:0000:3b:00.0",
        "numa:0",
        "nic:eth0",
        "rdma:mlx5_0",
        "rdma:mlx5_0:1",
    }
    gpu = next(record for record in records if record["identity"] == "gpu:GPU-0")
    assert gpu["node_id"] == "node-a"


def test_local_worker_identity_carries_authoritative_nvidia_physical_evidence(monkeypatch) -> None:
    import lead_engine.nvidia_provider as nvidia_provider

    gpu = GpuResource(
        node_id="node-a",
        gpu_id="0",
        gpu_uuid="GPU-real",
        vram_bytes=80 * 1024**3,
        pci_bus_id="0000:3b:00.0",
        numa_node=0,
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    snapshot = ProviderResourceSnapshot(
        provider_id="nvidia",
        domain_id="supercomputer-a",
        observed_at=1.0,
        nodes=(
            NodeResource(
                node_id="node-a",
                architecture="x86_64",
                cpu=CpuResource("node-a", 64, 512 * 1024**3),
                gpus=(gpu,),
                nic_names=("eth0",),
                state=ResourceState.AVAILABLE,
            ),
        ),
        evidence={
            "physical_fabric": {
                "components": [
                    {"component_type": "gpu", "identity": "gpu:GPU-real", "node_id": "node-a"}
                ],
                "relationships": [],
            }
        },
    )

    monkeypatch.setenv("THORIO_COMPUTE_DOMAIN", "supercomputer-a")
    monkeypatch.setattr(nvidia_provider.NvidiaProvider, "discover", lambda self: snapshot)

    identity = local_worker_identity("node-a")
    assert identity.domain_id == "supercomputer-a"
    assert identity.physical_fabric_evidence["physical_fabric"]["components"][0]["identity"] == "gpu:GPU-real"


class _FreeGpuProvider(FreeComputeProvider):
    provider_id = "free-provider"

    def discover_free(self):
        return ()

    def acquire_free(self, offer):
        acquisition_id = FreeComputeAcquisitionStore.acquisition_id(offer)
        return AcquiredCompute(
            provider_id=offer.provider_id,
            domain_id=offer.domain_id,
            offer_id=offer.offer_id,
            acquisition_id=acquisition_id,
            acquired_at=101.0,
            expires_at=200.0,
            gpu_capable=True,
            enrollment={"worker_id": "node-a", "acquisition_id": acquisition_id},
        )


def test_acquired_external_gpu_is_not_trusted_until_authenticated_physical_enrollment(tmp_path: Path) -> None:
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token")
    coordinator.register_free_compute_provider(_FreeGpuProvider())
    offer = FreeComputeOffer(
        provider_id="free-provider",
        domain_id="supercomputer-a",
        offer_id="offer-1",
        observed_at=100.0,
        expires_at=200.0,
        gpu_capable=True,
        no_cost=True,
        capacity_evidence={"source": "provider-observation", "gpu_count": 1},
    )
    acquired = coordinator.acquire_free_compute(offer)
    assert acquired.acquisition_id == FreeComputeAcquisitionStore.acquisition_id(offer)
    assert coordinator.free_compute_status()["eligible_verified_count"] == 0
    assert coordinator.free_compute_status()["eligible_acquired_count"] == 0

    identity = _identity()
    identity = WorkerIdentity(
        **{**identity.__dict__, "physical_fabric_evidence": {**identity.physical_fabric_evidence, "acquisition_id": acquired.acquisition_id}}
    )
    coordinator.register_worker(identity)

    status = coordinator.free_compute_status()
    assert status["eligible_acquired_count"] == 0
    assert status["eligible_verified_count"] == 1
    record = next(item for item in status["records"] if item["acquisition_id"] == acquired.acquisition_id)
    assert record["status"] == "verified"
    assert record["worker_id"] == "node-a"
    assert record["verification"]["gpu_discovery_state"] == "healthy"
    assert record["verification"]["gpu_resources"][0]["gpu_uuid"] == "GPU-0"
