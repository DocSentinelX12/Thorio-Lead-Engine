from lead_engine.compute_fabric_telemetry import summarize_route_health


def test_summarize_route_health_exposes_observed_trend_without_policy():
    summary = summarize_route_health([
        {"observed_at": 100.0, "latency_ms": 2.0, "success": True},
        {"observed_at": 200.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 300.0, "latency_ms": 5.0, "success": False},
    ])
    assert summary["sample_count"] == 3
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["failure_rate"] == 1 / 3
    assert summary["latest_observed_at"] == 300.0
    assert summary["latest_success"] is False
    assert summary["latest_latency_ms"] == 5.0
    assert summary["historical_mean_latency_ms"] == (2.0 + 3.0 + 5.0) / 3
    assert summary["latency_change_from_previous_ms"] == 2.0
    assert summary["latency_change_ratio"] == (5.0 / 3.0) - 1.0
    assert summary["consecutive_failures"] == 1
    assert summary["consecutive_successes"] == 0


def test_summarize_route_health_does_not_turn_missing_latency_into_synthetic_data():
    summary = summarize_route_health([
        {"observed_at": 100.0, "latency_ms": None, "success": True},
        {"observed_at": 200.0, "latency_ms": 4.0, "success": True},
    ])
    assert summary["sample_count"] == 2
    assert summary["latest_latency_ms"] == 4.0
    assert summary["historical_mean_latency_ms"] == 4.0
    assert summary["latency_change_from_previous_ms"] is None
    assert summary["latency_change_ratio"] is None


def test_summarize_route_health_empty_or_invalid_samples_are_evidence_empty():
    assert summarize_route_health([]) == {
        "sample_count": 0,
        "success_count": 0,
        "failure_count": 0,
    }
    assert summarize_route_health([{"observed_at": 1.0, "latency_ms": 2.0, "success": "yes"}]) == {
        "sample_count": 0,
        "success_count": 0,
        "failure_count": 0,
    }


def test_extract_execution_path_observations_requires_explicit_concrete_path_identity():
    from lead_engine.compute_fabric_telemetry import extract_execution_path_observations

    verification = {
        "placement_id": "placement-1",
        "execution_attempt_id": "attempt-1",
        "generation": 3,
        "process_evidence": [{
            "rank": 0,
            "gpu_binding": {"planned_physical_path": {"fabric_path_id": "fabric-path-1", "path_id": "fabric-path-1"}},
            "probe": {"rank": 0, "gpu_uuid": "GPU-0", "all_reduce_elapsed_ms": 2.5, "network_transport": "IB"},
        }],
    }
    assert extract_execution_path_observations(verification, observed_at=300.0) == (
        {"fabric_path_id": "fabric-path-1", "latency_us": 2500.0, "success": True, "observed_at": 300.0,
         "evidence": {"source": "observed_all_reduce", "placement_id": "placement-1", "execution_attempt_id": "attempt-1", "generation": 3, "rank": 0, "gpu_uuid": "GPU-0", "network_transport": "IB"}},
    )


def test_execution_without_exact_path_identity_cannot_update_physical_path():
    from lead_engine.compute_fabric_telemetry import extract_execution_path_observations

    verification = {"process_evidence": [{"rank": 0, "gpu_binding": {"planned_physical_path": {"node_id": "node-0"}},
        "probe": {"rank": 0, "gpu_uuid": "GPU-0", "all_reduce_elapsed_ms": 2.5}}]}
    assert extract_execution_path_observations(verification, observed_at=300.0) == ()


def test_fabric_launch_contract_binds_durable_adaptive_path_ids_per_gpu_pair():
    # Contract-level assertion: adaptive route IDs selected by placement must be
    # carried into the per-rank launch binding instead of being reconstructed.
    from lead_engine.compute_coordinator import ComputeCoordinator

    assert hasattr(ComputeCoordinator, "_adaptive_launch_routes")
    routes = ComputeCoordinator._adaptive_launch_routes(
        {"evidence": {"adaptive_routes": ({"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "path_id": "path-fast"},)}},
        ("gpu:u0", "gpu:u1"),
    )
    assert routes == ("path-fast",)
