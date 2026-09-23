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
