import json
import pytest
import tempfile
from pathlib import Path

from lead_engine.compute_bridge import REMOTE_SAFE_AGENTS
from lead_engine.compute_fabric_telemetry import aggregate_execution_metrics, extract_execution_metrics
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
        all_reduce_elapsed_ms=1.75,
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
        "all_reduce_elapsed_ms": 1.75,
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




def test_fabric_telemetry_extracts_only_observed_collective_timings():
    verification = {
        "process_evidence": [
            {
                "rank": 1,
                "gpu_binding": {"node_id": "node-b"},
                "probe": {
                    "rank": 1,
                    "gpu_uuid": "GPU-1",
                    "network_transport": "IB",
                    "all_reduce_elapsed_ms": 2.5,
                },
            },
            {
                "rank": 0,
                "gpu_binding": {"node_id": "node-a"},
                "probe": {
                    "rank": 0,
                    "gpu_uuid": "GPU-0",
                    "network_transport": "IB",
                    "all_reduce_elapsed_ms": 1.5,
                },
            },
            {
                "rank": 2,
                "probe": {
                    "rank": 2,
                    "gpu_uuid": "GPU-2",
                    "all_reduce_elapsed_ms": "not-a-measurement",
                },
            },
        ]
    }
    metrics = extract_execution_metrics(verification)
    assert [item["rank"] for item in metrics] == [0, 1]
    assert aggregate_execution_metrics(metrics) == {
        "sample_count": 2,
        "min_all_reduce_elapsed_ms": 1.5,
        "max_all_reduce_elapsed_ms": 2.5,
        "avg_all_reduce_elapsed_ms": 2.0,
        "transport": "IB",
    }


def test_coordinator_exposes_durable_distributed_fabric_execution_telemetry(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "test-token")
    with coordinator._connect() as connection:
        now = 1000.0
        connection.execute(
            """INSERT INTO compute_tasks
               (task_id,payload,status,worker_id,lease_token,lease_until,attempt_id,generation,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("task-telemetry", "{}", "leased", "worker-1", "lease", now + 300, "attempt-telemetry", 1, now, now),
        )
        connection.execute(
            """INSERT INTO compute_execution_attempts
               (attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at,allocation_id,rendezvous_endpoint)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            ("attempt-telemetry", "task-telemetry", 1, "worker-1", "leased",
             __import__("hashlib").sha256(b"lease").hexdigest(), now, None, "127.0.0.1:29500"),
        )
        connection.execute(
            """INSERT INTO compute_fabric_execution_metrics
               (metric_id,task_id,attempt_id,generation,worker_id,rank,gpu_uuid,node_id,transport,all_reduce_elapsed_ms,observed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("metric-seed-0","task-telemetry","attempt-telemetry",1,"worker-1",0,"GPU-0","worker-1","IB",2.0,now),
        )
        connection.execute(
            """INSERT INTO compute_fabric_execution_metrics
               (metric_id,task_id,attempt_id,generation,worker_id,rank,gpu_uuid,node_id,transport,all_reduce_elapsed_ms,observed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("metric-seed-1","task-telemetry","attempt-telemetry",1,"worker-1",1,"GPU-1","worker-2","IB",3.0,now),
        )
        connection.commit()
    result = coordinator.fabric_execution_metrics("attempt-telemetry", 1)
    assert result["sample_count"] == 2
    assert result["min_all_reduce_elapsed_ms"] == 2.0
    assert result["max_all_reduce_elapsed_ms"] == 3.0
    assert result["avg_all_reduce_elapsed_ms"] == 2.5
    assert [row["rank"] for row in result["samples"]] == [0, 1]

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




def _inventory_snapshot_for_quarantine():
    return ProviderResourceSnapshot(
        provider_id="provider",
        domain_id="domain",
        observed_at=1.0,
        nodes=(
            NodeResource(
                node_id="node-1",
                architecture="x86_64",
                cpu=CpuResource("node-1", 4, 8192),
                gpus=(GpuResource(
                    node_id="node-1",
                    gpu_id="gpu-0",
                    gpu_uuid="GPU-0",
                    vram_bytes=1,
                    health_state=ResourceState.HEALTHY,
                    availability_state=ResourceState.AVAILABLE,
                ),),
                state=ResourceState.AVAILABLE,
            ),
        ),
        authentication_state="authenticated",
        evidence={},
    )


def test_inventory_quarantines_one_failed_physical_path_with_durable_reason(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_inventory_snapshot_for_quarantine())
    key = "provider/domain/node-1/gpu/GPU-0"
    assert inventory.quarantine_resource(
        key,
        reason="NCCL selected an HCA port different from the scheduler's verified physical path",
        evidence={"failure_class": "planned_actual_physical_path_mismatch", "rdma_device": "mlx5_0", "rdma_port": 2},
    )
    resource = inventory.get(key)
    assert resource["state"] == ResourceState.QUARANTINED.value
    evidence = json.loads(resource["evidence_json"])
    assert evidence["quarantine"]["evidence"]["failure_class"] == "planned_actual_physical_path_mismatch"
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


def test_coordinator_quarantines_only_the_failed_physical_path(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = {
        "node_id": "node-1",
        "gpu_uuid": "GPU-0",
        "nic": "eth1",
        "rdma_device": "mlx5_1",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    snapshot = _inventory_snapshot_for_quarantine()
    snapshot = ProviderResourceSnapshot(
        provider_id=snapshot.provider_id,
        domain_id=snapshot.domain_id,
        observed_at=snapshot.observed_at,
        nodes=snapshot.nodes,
        authentication_state=snapshot.authentication_state,
        evidence={
            "network": {
                "gpu_nic_locality": [path],
                "rdma": {
                    "devices": [{"device": "mlx5_1"}],
                    "links": [{
                        "rdma_device": "mlx5_1",
                        "port": 1,
                        "link_layer": "InfiniBand",
                        "state": "ACTIVE",
                        "physical_state": "LINK_UP",
                    }],
                },
            },
        },
    )
    inventory.observe(snapshot)
    allocation_id = "allocation-path-isolation"
    resource_key = "provider/domain/node-1/gpu/GPU-0"
    inventory.reserve_allocation(allocation_id, "provider", "domain", [resource_key])
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "test-token", inventory=inventory)
    coordinator._quarantine_allocation_gpu_for_path_failure(
        allocation_id,
        "GPU-0",
        reason="NCCL selected a different HCA port",
        evidence={
            "failure_class": "planned_actual_physical_path_mismatch",
            "planned_physical_path": path,
        },
    )
    assert inventory.is_fabric_path_quarantined(path) is True
    assert inventory.get(resource_key)["state"] == ResourceState.RESERVED.value
