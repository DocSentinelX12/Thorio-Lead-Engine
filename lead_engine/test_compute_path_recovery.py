import json
import time

import pytest

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import (
    ComputeRequirements,
    CpuResource,
    GpuRequirements,
    GpuResource,
    NodeResource,
    ResourceState,
    WorkloadClass,
)
from lead_engine.compute_scheduler import ComputeScheduler, ComputeSchedulingError


def _snapshot(*, network):
    node_id = "node-a"
    gpu = GpuResource(
        node_id=node_id,
        gpu_id="gpu-0",
        gpu_uuid="GPU-0",
        model="NVIDIA Test GPU",
        vram_bytes=24 * 1024**3,
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    return ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(NodeResource(
            node_id=node_id,
            architecture="x86_64",
            cpu=CpuResource(node_id, 32, 128 * 1024**3),
            gpus=(gpu,),
            cuda_version="12.4",
            driver_version="550.54",
            nccl_version="2.21",
            state=ResourceState.AVAILABLE,
        ),),
        authentication_state="authenticated",
        evidence={"source": "verified-test-discovery", "network": network},
    )


def _network_evidence():
    return {
        "source": "verified-test-discovery",
        "gpu_nic_locality": [
            {
                "gpu_uuid": "GPU-0",
                "nic": "eth0",
                "rdma_device": "mlx5_0",
                "rdma_port": 1,
                "link_layer": "InfiniBand",
                "source": "sysfs",
            },
            {
                "gpu_uuid": "GPU-0",
                "nic": "eth1",
                "rdma_device": "mlx5_1",
                "rdma_port": 1,
                "link_layer": "InfiniBand",
                "source": "sysfs",
            },
        ],
        "rdma": {
            "devices": [
                {"device": "mlx5_0"},
                {"device": "mlx5_1"},
            ],
            "links": [
                {
                    "rdma_device": "mlx5_0",
                    "port": 1,
                    "link_layer": "InfiniBand",
                    "state": "ACTIVE",
                    "physical_state": "LINK_UP",
                },
                {
                    "rdma_device": "mlx5_1",
                    "port": 1,
                    "link_layer": "InfiniBand",
                    "state": "ACTIVE",
                    "physical_state": "LINK_UP",
                },
            ],
        },
    }


def test_quarantined_path_is_replaced_by_an_independently_verified_path(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    network = _network_evidence()
    inventory.observe(_snapshot(network=network))

    failed_path = {
        "node_id": "node-a",
        "gpu_uuid": "GPU-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    inventory.quarantine_fabric_path(
        failed_path,
        reason="NCCL selected an HCA path that failed physical verification",
        evidence={"failure_class": "planned_actual_physical_path_mismatch"},
    )

    allocation = ComputeScheduler(inventory).allocate(
        ComputeRequirements(
            WorkloadClass.MULTI_GPU,
            GpuRequirements(gpu_count=1, require_nccl=False),
        ),
        "reselection-allocation",
    )

    evidence = next(item for item in allocation.capability_evidence if item.get("gpu_uuid") == "GPU-0")
    paths = evidence["placement_decision"]["verified_gpu_nic_rdma_path"]
    assert len(paths) == 1
    assert paths[0]["rdma_device"] == "mlx5_1"
    assert paths[0]["nic"] == "eth1"
    assert inventory.is_fabric_path_quarantined(failed_path) is True


def test_quarantined_only_path_cannot_satisfy_multi_node_nccl_placement(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    network = _network_evidence()
    inventory.observe(_snapshot(network=network))

    failed_path = {
        "node_id": "node-a",
        "gpu_uuid": "GPU-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    inventory.quarantine_fabric_path(
        failed_path,
        reason="only verified distributed path failed",
        evidence={"failure_class": "rdma_link_down"},
    )
    second_node = GpuResource(
        node_id="node-b",
        gpu_id="gpu-0",
        gpu_uuid="GPU-1",
        model="NVIDIA Test GPU",
        vram_bytes=24 * 1024**3,
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(NodeResource(
            node_id="node-b",
            architecture="x86_64",
            cpu=CpuResource("node-b", 32, 128 * 1024**3),
            gpus=(second_node,),
            cuda_version="12.4",
            driver_version="550.54",
            nccl_version="2.21",
            state=ResourceState.AVAILABLE,
        ),),
        authentication_state="authenticated",
        evidence={"source": "verified-test-discovery", "network": {
            "source": "verified-test-discovery",
            "network_domains": {"node-a": "fabric-a", "node-b": "fabric-a"},
        }},
    ))

    with pytest.raises(ComputeSchedulingError, match="no compatible multi-node allocation"):
        ComputeScheduler(inventory).allocate(
            ComputeRequirements(
                WorkloadClass.MULTI_NODE_GPU,
                GpuRequirements(gpu_count=2, require_nccl=True),
                same_node=False,
            ),
            "reselection-no-alternate",
        )


def test_reselection_never_clears_quarantine_without_matching_physical_evidence(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(network=_network_evidence()))
    path = {
        "node_id": "node-a",
        "gpu_uuid": "GPU-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    inventory.quarantine_fabric_path(path, reason="path failure")

    with pytest.raises(ValueError):
        inventory.revalidate_fabric_path(
            path,
            verification={
                "verified": True,
                **{**path, "rdma_device": "mlx5_1"},
            },
        )
    assert inventory.is_fabric_path_quarantined(path) is True

    assert inventory.revalidate_fabric_path(path, verification={"verified": True, **path}) is True
    assert inventory.is_fabric_path_quarantined(path) is False


def test_launch_plan_rejects_a_path_quarantined_after_allocation(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=60,
        inventory=inventory,
    )
    network_a = _network_evidence()
    network_a["network_domains"] = {"node-a": "fabric-a"}
    inventory.observe(_snapshot(network=network_a))

    path_b = {
        "gpu_uuid": "GPU-1",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
        "source": "sysfs",
    }
    network_b = {
        "source": "verified-test-discovery",
        "network_domains": {"node-b": "fabric-a"},
        "gpu_nic_locality": [{**path_b}],
        "rdma": {
            "devices": [{"device": "mlx5_0"}],
            "links": [{
                "rdma_device": "mlx5_0",
                "port": 1,
                "link_layer": "InfiniBand",
                "state": "ACTIVE",
                "physical_state": "LINK_UP",
            }],
        },
    }
    gpu_b = GpuResource(
        node_id="node-b",
        gpu_id="gpu-0",
        gpu_uuid="GPU-1",
        model="NVIDIA Test GPU",
        vram_bytes=24 * 1024**3,
        health_state=ResourceState.HEALTHY,
        availability_state=ResourceState.AVAILABLE,
    )
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(NodeResource(
            node_id="node-b",
            architecture="x86_64",
            cpu=CpuResource("node-b", 32, 128 * 1024**3),
            gpus=(gpu_b,),
            cuda_version="12.4",
            driver_version="550.54",
            nccl_version="2.21",
            state=ResourceState.AVAILABLE,
        ),),
        authentication_state="authenticated",
        evidence={"source": "verified-test-discovery", "network": network_b},
    ))

    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2, "require_nccl": True},
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed is not None
    assert claimed["task_id"] == task_id
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    endpoint = f"10.0.0.5:29400"

    with coordinator._connect() as connection:
        connection.execute(
            "UPDATE compute_execution_attempts SET rendezvous_endpoint=? WHERE attempt_id=?",
            (endpoint, attempt_id),
        )
        connection.commit()

    failed_path = {
        "node_id": "node-a",
        "gpu_uuid": "GPU-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    inventory.quarantine_fabric_path(failed_path, reason="path failed after allocation")

    with pytest.raises(ValueError, match="physical path is quarantined before launch"):
        coordinator.fabric_launch_plan(attempt_id, endpoint)
