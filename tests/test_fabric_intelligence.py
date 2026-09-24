from __future__ import annotations

from lead_engine.compute_fabric_telemetry import (
    workload_performance_key,
    summarize_route_health,
)


def test_workload_performance_key_separates_collective_workloads():
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    first = workload_performance_key(
        path,
        {
            "workload_class": "multi_gpu",
            "collective": "all_reduce",
            "world_size": 8,
            "message_size_bytes": 1048576,
            "dtype": "bf16",
        },
    )
    second = workload_performance_key(
        path,
        {
            "workload_class": "multi_gpu",
            "collective": "all_reduce",
            "world_size": 8,
            "message_size_bytes": 16777216,
            "dtype": "bf16",
        },
    )
    assert first
    assert first != second


def test_workload_performance_key_is_order_independent():
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    a = workload_performance_key(path, {"world_size": 8, "collective": "all_reduce", "dtype": "bf16"})
    b = workload_performance_key(path, {"dtype": "bf16", "collective": "all_reduce", "world_size": 8})
    assert a == b


def test_route_health_summary_exposes_observed_regression_without_threshold_policy():
    samples = [
        {"observed_at": 10.0, "latency_ms": 4.0, "success": True},
        {"observed_at": 20.0, "latency_ms": 5.0, "success": True},
        {"observed_at": 30.0, "latency_ms": 9.0, "success": True},
        {"observed_at": 40.0, "latency_ms": 9.0, "success": False},
    ]
    summary = summarize_route_health(samples)
    assert summary["sample_count"] == 4
    assert summary["success_count"] == 3
    assert summary["failure_count"] == 1
    assert summary["latest_latency_ms"] == 9.0
    assert summary["historical_mean_latency_ms"] == 6.75
    assert summary["latency_delta_from_mean_ms"] == 2.25
    assert summary["failure_rate"] == 0.25


def test_route_health_summary_preserves_unknown_evidence():
    summary = summarize_route_health([])
    assert summary == {"sample_count": 0, "success_count": 0, "failure_count": 0}


def test_scheduler_uses_workload_specific_history_before_legacy_path_history(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import ComputeRequirements, GpuRequirements, WorkloadClass, CpuResource, GpuResource, NodeResource, ResourceState
    from lead_engine.compute_scheduler import ComputeScheduler
    import time

    def gpu(node, gid, uuid):
        return GpuResource(
            node_id=node, gpu_id=gid, gpu_uuid=uuid, vram_bytes=24 * 1024**3,
            compute_capability="8.0", health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
        )

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="p", domain_id="d", observed_at=time.time(),
        nodes=(NodeResource(
            node_id="n", architecture="x86_64",
            cpu=CpuResource(node_id="n", cpu_count=8, memory_bytes=64 * 1024**3),
            gpus=(gpu("n", "g0", "u0"), gpu("n", "g1", "u1")),
            state=ResourceState.HEALTHY,
        ),),
        authentication_state="authenticated",
        evidence={"network": {
            "source": "test",
            "gpu_nic_locality": [
                {"gpu_uuid": "u0", "nic": "e0", "rdma_device": "r0", "rdma_port": 1, "link_layer": "ib"},
                {"gpu_uuid": "u1", "nic": "e1", "rdma_device": "r1", "rdma_port": 1, "link_layer": "ib"},
            ],
            "rdma": {"devices": [{"device": "r0"}, {"device": "r1"}], "links": [
                {"rdma_device": "r0", "port": 1, "link_layer": "ib", "state": "ACTIVE", "physical_state": "LINK_UP"},
                {"rdma_device": "r1", "port": 1, "link_layer": "ib", "state": "ACTIVE", "physical_state": "LINK_UP"},
            ]},
        }},
    ))
    from lead_engine.compute_fabric_telemetry import workload_performance_key, physical_path_key
    paths = {
        "u0": {"node_id": "n", "gpu_uuid": "u0", "nic": "e0", "rdma_device": "r0", "rdma_port": 1, "link_layer": "ib"},
        "u1": {"node_id": "n", "gpu_uuid": "u1", "nic": "e1", "rdma_device": "r1", "rdma_port": 1, "link_layer": "ib"},
    }
    workload = {"workload_class": "multi_gpu", "collective": "all_reduce", "world_size": 2, "message_size_bytes": 1048576}
    history = {
        workload_performance_key(paths["u0"], workload): {"avg_all_reduce_elapsed_ms": 2.0, "sample_count": 5},
        workload_performance_key(paths["u1"], workload): {"avg_all_reduce_elapsed_ms": 8.0, "sample_count": 5},
        physical_path_key(paths["u0"]): {"avg_all_reduce_elapsed_ms": 99.0, "sample_count": 100},
        physical_path_key(paths["u1"]): {"avg_all_reduce_elapsed_ms": 1.0, "sample_count": 100},
    }
    scheduler = ComputeScheduler(inventory, performance_history_provider=lambda: history)
    allocation = scheduler.allocate(
        ComputeRequirements(
            WorkloadClass.MULTI_GPU,
            GpuRequirements(gpu_count=1),
            performance_signature=tuple(workload.items()),
        ),
        "workload-specific",
    )
    assert allocation.resource_ids[-1] == "n/g0"


def test_route_health_observations_are_durable_and_idempotent(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    first = inventory.record_fabric_route_observation(
        path, latency_ms=4.0, success=True, observed_at=10.0,
    )
    second = inventory.record_fabric_route_observation(
        path, latency_ms=4.0, success=True, observed_at=10.0,
    )
    inventory.record_fabric_route_observation(
        path, latency_ms=9.0, success=False, observed_at=20.0,
    )
    assert first == second
    health = inventory.fabric_route_health_index()[inventory.fabric_path_key(path)]
    assert health["sample_count"] == 2
    assert health["failure_count"] == 1
    assert health["latest_latency_ms"] == 9.0


def test_execution_metrics_carry_explicit_workload_identity():
    from lead_engine.compute_fabric_telemetry import extract_execution_metrics

    verification = {
        "workload": {
            "workload_class": "multi_gpu",
            "collective": "all_reduce",
            "world_size": 4,
            "message_size_bytes": 4096,
            "dtype": "fp16",
        },
        "process_evidence": [{
            "rank": 0,
            "gpu_binding": {
                "node_id": "node-a",
                "planned_physical_path": {
                    "node_id": "node-a",
                    "gpu_uuid": "gpu-0",
                    "nic": "eth0",
                    "rdma_device": "mlx5_0",
                    "rdma_port": 1,
                    "link_layer": "InfiniBand",
                },
            },
            "probe": {
                "rank": 0,
                "gpu_uuid": "gpu-0",
                "network_transport": "nccl",
                "all_reduce_elapsed_ms": 3.5,
            },
        }],
    }
    metric = extract_execution_metrics(verification)[0]
    assert metric["workload_signature"]["message_size_bytes"] == 4096
    assert metric["workload_key"]


def test_inventory_route_health_exposes_predictive_failure_degradation_without_new_storage(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    workload_key = "workload-a"
    for observed_at, success in ((1.0, True), (2.0, True), (3.0, False), (4.0, False)):
        inventory.record_fabric_route_observation(
            path,
            latency_ms=3.0,
            success=success,
            observed_at=observed_at,
            evidence={"workload_key": workload_key, "fabric_path_id": "path-a"},
            fabric_path_id="path-a",
        )

    health = inventory.fabric_route_health_index()["path-a"]
    assert health["failure_count"] == 2
    assert health["predictive_failure_degradation"]["state"] == "failure_pattern"
    assert health["predictive_failure_by_workload_key"][workload_key]["state"] == "failure_pattern"
