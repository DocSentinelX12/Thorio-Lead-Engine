import json
import pytest
import tempfile
from pathlib import Path

from lead_engine.compute_bridge import REMOTE_SAFE_AGENTS
from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_pool import WorkerIdentity
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
from lead_engine.nccl_all_reduce_probe import build_probe_evidence
from lead_engine.nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


def test_nccl_probe_evidence_builder_contains_only_observed_core_fields():
    evidence = build_probe_evidence(
        rank=1,
        world_size=4,
        nnodes=2,
        expected_sum=10,
        gpu_uuid="GPU-test-1",
        hostname="worker-2",
    )
    assert evidence == {
        "backend": "nccl",
        "rank": 1,
        "world_size": 4,
        "nnodes": 2,
        "local_rank": 0,
        "collective": "all_reduce",
        "expected_sum": 10,
        "verified_on_gpu": True,
        "gpu_uuid": "GPU-test-1",
        "hostname": "worker-2",
    }


def test_nccl_network_evidence_records_only_explicit_remote_rank_edges():
    evidence = NvidiaRuntime.parse_nccl_network_evidence(
        """
NCCL INFO Using network IB
NCCL INFO Channel 00/0 : 0[0] -> 1[1] [send] via NET/IB/0
NCCL INFO Channel 01/0 : 0[0] -> 3[3] [recv] via NET/IB/1
"""
    )
    assert evidence["network_transport"] == "IB"
    assert evidence["peer_connections"] == (
        {"channel": "00/0", "local_rank": 0, "peer_rank": 1, "direction": "send", "transport": "IB/0"},
        {"channel": "01/0", "local_rank": 0, "peer_rank": 3, "direction": "recv", "transport": "IB/1"},
    )


def _worker():
    return WorkerIdentity(
        "worker-1",
        "host",
        "x86_64",
        4,
        8192,
        ("lead-processing", "engineering_demand_discovery"),
    )


def test_nvidia_runtime_reconciles_planned_physical_path_against_actual_hca_port():
    planned = {
        "gpu_uuid": "GPU-1",
        "nic": "eth1",
        "nic_pci_bus_id": "0000:41:00.0",
        "rdma_device": "mlx5_1",
        "rdma_port": 1,
        "rdma_pci_bus_id": "0000:41:00.0",
        "link_layer": "InfiniBand",
    }
    actual = {
        "gpu_uuid": "GPU-1",
        "gpu_nic_locality": {
            "gpu_uuid": "GPU-1",
            "nic": "eth1",
            "nic_pci_bus_id": "0000:41:00.0",
            "rdma_device": "mlx5_1",
            "rdma_port": 1,
            "rdma_pci_bus_id": "0000:41:00.0",
            "link_layer": "InfiniBand",
        },
        "verified_hca_selections": [
            {"device": "mlx5_1", "port": 1, "transport": "IB"},
        ],
    }
    result = NvidiaRuntime.reconcile_planned_physical_path(planned, actual)
    assert result["verified"] is True
    assert result["rdma_device"] == "mlx5_1"
    assert result["rdma_port"] == 1


def test_nvidia_runtime_rejects_planned_physical_path_when_nccl_selects_different_port():
    planned = {
        "gpu_uuid": "GPU-1",
        "nic": "eth1",
        "nic_pci_bus_id": "0000:41:00.0",
        "rdma_device": "mlx5_1",
        "rdma_port": 1,
        "rdma_pci_bus_id": "0000:41:00.0",
        "link_layer": "InfiniBand",
    }
    actual = {
        "gpu_uuid": "GPU-1",
        "gpu_nic_locality": {
            "gpu_uuid": "GPU-1",
            "nic": "eth1",
            "nic_pci_bus_id": "0000:41:00.0",
            "rdma_device": "mlx5_1",
            "rdma_port": 2,
            "rdma_pci_bus_id": "0000:41:00.0",
            "link_layer": "InfiniBand",
        },
        "verified_hca_selections": [
            {"device": "mlx5_1", "port": 2, "transport": "IB"},
        ],
    }
    with pytest.raises(NvidiaRuntimeError, match="planned physical path"):
        NvidiaRuntime.reconcile_planned_physical_path(planned, actual)


def test_inventory_quarantines_one_failed_physical_path_with_durable_reason(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot_with_gpu("GPU-0"))
    key = "provider/domain/node-1/gpu/GPU-0"
    assert inventory.quarantine_resource(
        key,
        reason="NCCL selected an HCA port different from the scheduler's verified physical path",
        evidence={"failure_class": "planned_actual_physical_path_mismatch", "rdma_device": "mlx5_0", "rdma_port": 2},
    )
    resource = inventory.get(key)
    assert resource["state"] == ResourceState.QUARANTINED.value
    evidence = json.loads(resource["evidence_json"])
    assert evidence["quarantine"]["failure_class"] == "planned_actual_physical_path_mismatch"
    assert key not in {row["resource_key"] for row in inventory.eligible()}


def test_nvidia_runtime_rejects_inactive_rdma_link_as_verified_path():
    log = "NCCL INFO Using network IB\nNCCL INFO NET/IB : Using [0]mlx5_1:1/IB"
    with pytest.raises(NvidiaRuntimeError, match="not active"):
        NvidiaRuntime.validate_nccl_transport_against_rdma(
            log,
            {
                "devices": [{"device": "mlx5_1"}],
                "links": [{
                    "rdma_device": "mlx5_1",
                    "port": 1,
                    "netdev": "eth1",
                    "pci_bus_id": "0000:41:00.0",
                    "state": "DOWN",
                    "physical_state": "LINK_DOWN",
                    "link_layer": "InfiniBand",
                }],
            },
            gpu_uuid="GPU-1",
            gpu_nic_locality=[{
                "gpu_uuid": "GPU-1",
                "nic": "eth1",
                "nic_pci_bus_id": "0000:41:00.0",
            }],
        )
