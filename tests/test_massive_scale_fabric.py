"""Massive-scale control-plane proof for the GPU fabric.

These tests exercise the real durable inventory and fleet intelligence paths.
They intentionally do not pretend that CI has physical GPUs. They prove that
the control plane remains correct and restart-safe at fleet scale.
"""
from __future__ import annotations

import time

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


SUPERCOMPUTER_COUNT = 12
NODES_PER_SUPERCOMPUTER = 64
GPUS_PER_NODE = 8


def _snapshot(supercomputer: int, observed_at: float) -> ProviderResourceSnapshot:
    provider = f"supercomputer-{supercomputer:02d}"
    domain = f"fabric-domain-{supercomputer:02d}"
    nodes = []
    for node_index in range(NODES_PER_SUPERCOMPUTER):
        node_id = f"{provider}-node-{node_index:03d}"
        gpus = tuple(
            GpuResource(
                node_id=node_id,
                gpu_id=f"gpu-{gpu_index:02d}",
                gpu_uuid=f"{provider}-uuid-{node_index:03d}-{gpu_index:02d}",
                model="NVIDIA H100",
                vram_bytes=80 * 1024**3,
                compute_capability="9.0",
                driver_version="550.54.15",
                cuda_version="12.4",
                numa_node=gpu_index // 4,
                topology_domain=f"{provider}-topology-{node_index:03d}",
                health_state=ResourceState.HEALTHY,
                availability_state=ResourceState.AVAILABLE,
            )
            for gpu_index in range(GPUS_PER_NODE)
        )
        nodes.append(
            NodeResource(
                node_id=node_id,
                architecture="x86_64",
                cpu=CpuResource(node_id, 128, 512 * 1024**3),
                gpus=gpus,
                driver_version="550.54.15",
                cuda_version="12.4",
                nccl_version="2.21",
                state=ResourceState.AVAILABLE,
            )
        )
    return ProviderResourceSnapshot(
        provider_id=provider,
        domain_id=domain,
        observed_at=observed_at,
        nodes=tuple(nodes),
        authentication_state="authenticated",
        evidence={"source": "massive_scale_control_plane_proof"},
    )


def test_twelve_supercomputer_fleet_persists_and_aggregates_exact_capacity(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "massive-scale.sqlite3"))
    observed_at = time.time()

    for supercomputer in range(SUPERCOMPUTER_COUNT):
        inventory.observe(_snapshot(supercomputer, observed_at))

    expected_gpus = SUPERCOMPUTER_COUNT * NODES_PER_SUPERCOMPUTER * GPUS_PER_NODE
    expected_nodes = SUPERCOMPUTER_COUNT * NODES_PER_SUPERCOMPUTER
    expected_resources = expected_nodes * (GPUS_PER_NODE + 1)

    summary = inventory.fleet_resource_intelligence(now=observed_at + 1)

    assert summary["totals"]["gpu"]["TOTAL"] == expected_gpus
    assert summary["totals"]["nodes"]["TOTAL"] == expected_nodes
    assert summary["totals"]["resources"]["TOTAL"] == expected_resources
    assert summary["totals"]["eligible"] == expected_resources
    assert summary["totals"]["gpu"]["AVAILABLE"] == expected_gpus
    assert summary["totals"]["gpu"]["known_vram_bytes"] == expected_gpus * 80 * 1024**3
    assert len(summary["provider_domains"]) == SUPERCOMPUTER_COUNT
    assert all(
        item["gpu"]["max_available_per_node"] == GPUS_PER_NODE
        for item in summary["provider_domains"].values()
    )


def test_massive_scale_reobservation_is_idempotent_and_restart_safe(tmp_path):
    db = str(tmp_path / "massive-scale-restart.sqlite3")
    inventory = ComputeInventory(db)
    observed_at = time.time()

    for supercomputer in range(SUPERCOMPUTER_COUNT):
        snapshot = _snapshot(supercomputer, observed_at)
        inventory.observe(snapshot)
        inventory.observe(
            _snapshot(supercomputer, observed_at + 1)
        )

    expected_resources = (
        SUPERCOMPUTER_COUNT
        * NODES_PER_SUPERCOMPUTER
        * (GPUS_PER_NODE + 1)
    )
    assert len(inventory.resources()) == expected_resources

    reopened = ComputeInventory(db)
    summary = reopened.fleet_resource_intelligence(now=observed_at + 2)

    assert len(reopened.resources()) == expected_resources
    assert summary["totals"]["gpu"]["TOTAL"] == SUPERCOMPUTER_COUNT * NODES_PER_SUPERCOMPUTER * GPUS_PER_NODE
    assert summary["latest_observed_at"] == observed_at + 1


def test_massive_scale_state_changes_remain_exact_and_capacity_is_never_fabricated(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "massive-scale-states.sqlite3"))
    observed_at = time.time()

    for supercomputer in range(SUPERCOMPUTER_COUNT):
        inventory.observe(_snapshot(supercomputer, observed_at))

    resources = [
        item for item in inventory.resources()
        if item["resource_type"] == "gpu"
    ]
    reserved = resources[:12]
    degraded = resources[12:24]
    quarantined = resources[24:36]

    for item in reserved:
        assert inventory.mark_state(item["resource_key"], ResourceState.RESERVED)
    for item in degraded:
        assert inventory.mark_state(item["resource_key"], ResourceState.DEGRADED)
    for item in quarantined:
        assert inventory.mark_state(item["resource_key"], ResourceState.QUARANTINED)

    summary = inventory.fleet_resource_intelligence(now=observed_at + 1)

    assert summary["totals"]["gpu"]["RESERVED"] == 12
    assert summary["totals"]["gpu"]["DEGRADED"] == 12
    assert summary["totals"]["gpu"]["QUARANTINED"] == 12
    assert summary["totals"]["gpu"]["AVAILABLE"] == len(resources) - 36
    assert summary["totals"]["eligible"] == summary["totals"]["resources"]["TOTAL"] - 36
    assert summary["totals"]["gpu"]["known_vram_bytes"] == len(resources) * 80 * 1024**3
    assert summary["totals"]["gpu"]["available_known_vram_bytes"] == (len(resources) - 36) * 80 * 1024**3


def test_massive_scale_fleet_never_crosses_provider_domain_boundaries(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "massive-scale-boundaries.sqlite3"))
    observed_at = time.time()

    for supercomputer in range(SUPERCOMPUTER_COUNT):
        inventory.observe(_snapshot(supercomputer, observed_at))

    summary = inventory.fleet_resource_intelligence(now=observed_at + 1)

    for index in range(SUPERCOMPUTER_COUNT):
        scope = f"supercomputer-{index:02d}/fabric-domain-{index:02d}"
        item = summary["provider_domains"][scope]
        assert item["provider_id"] == f"supercomputer-{index:02d}"
        assert item["domain_id"] == f"fabric-domain-{index:02d}"
        assert item["nodes"]["TOTAL"] == NODES_PER_SUPERCOMPUTER
        assert item["gpu"]["TOTAL"] == NODES_PER_SUPERCOMPUTER * GPUS_PER_NODE
        assert len(item["by_node"]) == NODES_PER_SUPERCOMPUTER
