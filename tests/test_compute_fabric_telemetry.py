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
            "gpu_binding": {"planned_physical_path": {"fabric_path_id": "fabric-path-1", "path_id": "fabric-path-1"}, "observed_fabric_path_id": "fabric-path-1"},
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


def test_predict_route_evidence_classifies_a_measurable_degrading_trend():
    from lead_engine.compute_fabric_telemetry import predict_route_evidence
    result = predict_route_evidence([
        {"observed_at": 100.0, "latency_ms": 2.0, "success": True},
        {"observed_at": 200.0, "latency_ms": 2.1, "success": True},
        {"observed_at": 300.0, "latency_ms": 3.8, "success": True},
        {"observed_at": 400.0, "latency_ms": 4.0, "success": True},
    ])
    assert result["state"] == "degrading"
    assert result["sample_count"] == 4
    assert result["baseline_latency_ms"] == 2.05
    assert result["recent_latency_ms"] == 3.9
    assert result["trend_delta_ms"] == 1.85


def test_predict_route_evidence_requires_temporal_evidence_and_does_not_invent_values():
    from lead_engine.compute_fabric_telemetry import predict_route_evidence
    result = predict_route_evidence([
        {"observed_at": 100.0, "latency_ms": None, "success": True},
        {"observed_at": 200.0, "latency_ms": 4.0, "success": True},
    ])
    assert result["state"] == "insufficient_evidence"
    assert result["baseline_latency_ms"] == 4.0
    assert result["recent_latency_ms"] == 4.0
    assert result["trend_delta_ms"] is None


def test_predict_route_evidence_can_classify_improvement_and_stability():
    from lead_engine.compute_fabric_telemetry import predict_route_evidence
    improving = predict_route_evidence([
        {"observed_at": 100.0, "latency_ms": 5.0, "success": True},
        {"observed_at": 200.0, "latency_ms": 4.8, "success": True},
        {"observed_at": 300.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 400.0, "latency_ms": 2.9, "success": True},
    ])
    stable = predict_route_evidence([
        {"observed_at": 100.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 200.0, "latency_ms": 3.1, "success": True},
        {"observed_at": 300.0, "latency_ms": 2.9, "success": True},
        {"observed_at": 400.0, "latency_ms": 3.2, "success": True},
    ])
    assert improving["state"] == "improving"
    assert stable["state"] == "stable"


def test_predict_route_evidence_is_not_false_certainty_for_noisy_observations():
    from lead_engine.compute_fabric_telemetry import predict_route_evidence
    result = predict_route_evidence([
        {"observed_at": 100.0, "latency_ms": 1.0, "success": True},
        {"observed_at": 200.0, "latency_ms": 5.0, "success": True},
        {"observed_at": 300.0, "latency_ms": 1.2, "success": True},
        {"observed_at": 400.0, "latency_ms": 4.8, "success": True},
    ])
    assert result["state"] == "insufficient_evidence"


def test_summarize_route_health_keeps_predictive_evidence_scoped_to_explicit_workload_keys():
    summary = summarize_route_health([
        {"observed_at": 100.0, "latency_ms": 2.0, "success": True, "evidence": {"workload_key": "workload-a"}},
        {"observed_at": 200.0, "latency_ms": 2.1, "success": True, "evidence": {"workload_key": "workload-a"}},
        {"observed_at": 300.0, "latency_ms": 3.8, "success": True, "evidence": {"workload_key": "workload-a"}},
        {"observed_at": 400.0, "latency_ms": 4.0, "success": True, "evidence": {"workload_key": "workload-a"}},
        {"observed_at": 100.0, "latency_ms": 5.0, "success": True, "evidence": {"workload_key": "workload-b"}},
        {"observed_at": 200.0, "latency_ms": 4.9, "success": True, "evidence": {"workload_key": "workload-b"}},
        {"observed_at": 300.0, "latency_ms": 3.1, "success": True, "evidence": {"workload_key": "workload-b"}},
        {"observed_at": 400.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "workload-b"}},
    ])
    assert summary["predictive_by_workload_key"]["workload-a"]["state"] == "degrading"
    assert summary["predictive_by_workload_key"]["workload-b"]["state"] == "improving"


def test_predict_route_evidence_does_not_treat_non_latency_failures_as_latency_measurements():
    from lead_engine.compute_fabric_telemetry import predict_route_evidence
    result = predict_route_evidence([
        {"observed_at": 100.0, "latency_ms": None, "success": False},
        {"observed_at": 200.0, "latency_ms": 2.0, "success": True},
        {"observed_at": 300.0, "latency_ms": None, "success": False},
        {"observed_at": 400.0, "latency_ms": 2.1, "success": True},
    ])
    assert result["state"] == "insufficient_evidence"
    assert result["latency_sample_count"] == 2


def test_derive_multidimensional_workload_evidence_preserves_explicit_dimensions_only():
    from lead_engine.compute_fabric_telemetry import derive_multidimensional_workload_evidence
    result = derive_multidimensional_workload_evidence([
        {"observed_at": 100.0, "latency_ms": 2.0, "success": True, "evidence": {
            "workload_key": "workload-a",
            "workload_signature": {"workload_class": "gpu_required", "collective": "all_reduce", "world_size": 8, "message_size_bytes": 4096, "dtype": "fp16", "reduce_op": "sum", "algorithm": "ring", "protocol": "simple"},
        }},
        {"observed_at": 200.0, "latency_ms": 2.2, "success": True, "evidence": {
            "workload_key": "workload-b",
            "workload_signature": {"workload_class": "gpu_required", "collective": "all_reduce", "world_size": 64, "message_size_bytes": 4096, "dtype": "bf16"},
        }},
    ])
    assert result["state"] == "observed"
    by_key = {item["workload_key"]: item for item in result["by_workload_key"]}
    assert by_key["workload-a"]["dimensions"]["world_size"] == 8
    assert by_key["workload-b"]["dimensions"]["dtype"] == "bf16"
    assert "protocol" not in by_key["workload-b"]["dimensions"]


def test_derive_multidimensional_workload_evidence_keeps_sparse_and_unidentified_samples_neutral():
    from lead_engine.compute_fabric_telemetry import derive_multidimensional_workload_evidence
    result = derive_multidimensional_workload_evidence([
        {"observed_at": 100.0, "latency_ms": 2.0, "success": True, "evidence": {"workload_key": "workload-a", "workload_signature": {"collective": "all_reduce"}}},
        {"observed_at": 200.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "workload-a"}},
    ])
    assert result["workload_combination_count"] == 1
    assert result["by_workload_key"][0]["sample_count"] == 1


def test_summarize_route_health_exposes_multidimensional_workload_evidence_without_cross_contamination():
    summary = summarize_route_health([
        {"observed_at": 100.0, "latency_ms": 2.0, "success": True, "evidence": {"workload_key": "workload-a", "workload_signature": {"collective": "all_reduce", "world_size": 8, "message_size_bytes": 1024}}},
        {"observed_at": 200.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "workload-b", "workload_signature": {"collective": "all_gather", "world_size": 8, "message_size_bytes": 1024}}},
    ])
    assert summary["multidimensional_by_workload_key"]["workload-a"]["dimensions"]["collective"] == "all_reduce"
    assert summary["multidimensional_by_workload_key"]["workload-b"]["dimensions"]["collective"] == "all_gather"


def test_execution_path_observations_persist_explicit_workload_signature():
    from lead_engine.compute_fabric_telemetry import extract_execution_path_observations
    verification = {
        "placement_id": "placement-1", "execution_attempt_id": "attempt-1", "generation": 2,
        "workload_signature": {"collective": "all_reduce", "world_size": 8, "message_size_bytes": 4096, "dtype": "fp16", "algorithm": "ring", "protocol": "simple"},
        "process_evidence": [{
            "rank": 0,
            "gpu_binding": {"planned_physical_path": {"node_id": "node-0", "gpu_uuid": "GPU-0", "nic": "nic0", "nic_pci_bus_id": "0000:01:00.0", "rdma_device": "rdma0", "rdma_port": 1, "rdma_pci_bus_id": "0000:02:00.0", "link_layer": "infiniband", "path_id": "fabric-path-1"}, "observed_fabric_path_id": "fabric-path-1"},
            "probe": {"rank": 0, "gpu_uuid": "GPU-0", "all_reduce_elapsed_ms": 2.5, "network_transport": "IB"},
        }],
    }
    evidence = extract_execution_path_observations(verification, observed_at=300.0)[0]["evidence"]
    assert evidence["workload_signature"] == verification["workload_signature"]


def test_predict_failure_degradation_evidence_detects_trailing_failure_pattern_without_prediction_score():
    from lead_engine.compute_fabric_telemetry import predict_failure_degradation_evidence
    evidence = predict_failure_degradation_evidence([
        {"observed_at": 1.0, "latency_ms": 2.0, "success": True},
        {"observed_at": 2.0, "latency_ms": 2.1, "success": True},
        {"observed_at": 3.0, "latency_ms": 2.2, "success": False},
        {"observed_at": 4.0, "latency_ms": None, "success": False},
    ])
    assert evidence["state"] == "failure_pattern"
    assert evidence["consecutive_failures"] == 2
    assert "failure_probability" not in evidence


def test_predict_failure_degradation_evidence_detects_latency_degradation_without_failures():
    from lead_engine.compute_fabric_telemetry import predict_failure_degradation_evidence
    evidence = predict_failure_degradation_evidence([
        {"observed_at": 1.0, "latency_ms": 2.0, "success": True},
        {"observed_at": 2.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 3.0, "latency_ms": 4.0, "success": True},
        {"observed_at": 4.0, "latency_ms": 5.0, "success": True},
    ])
    assert evidence["state"] == "degrading"


def test_predict_failure_degradation_evidence_marks_consistent_success_as_stable():
    from lead_engine.compute_fabric_telemetry import predict_failure_degradation_evidence
    evidence = predict_failure_degradation_evidence([
        {"observed_at": 1.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 2.0, "latency_ms": 3.1, "success": True},
        {"observed_at": 3.0, "latency_ms": 2.9, "success": True},
        {"observed_at": 4.0, "latency_ms": 3.0, "success": True},
    ])
    assert evidence["state"] == "stable"
    assert evidence["consecutive_successes"] == 4


def test_predict_failure_degradation_evidence_keeps_sparse_and_noisy_history_insufficient():
    from lead_engine.compute_fabric_telemetry import predict_failure_degradation_evidence
    sparse = predict_failure_degradation_evidence([
        {"observed_at": 1.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 2.0, "latency_ms": None, "success": False},
    ])
    noisy = predict_failure_degradation_evidence([
        {"observed_at": 1.0, "latency_ms": 2.0, "success": True},
        {"observed_at": 2.0, "latency_ms": 8.0, "success": True},
        {"observed_at": 3.0, "latency_ms": 3.0, "success": True},
        {"observed_at": 4.0, "latency_ms": 7.0, "success": True},
    ])
    assert sparse["state"] == "insufficient_evidence"
    assert noisy["state"] == "insufficient_evidence"


def test_predict_failure_degradation_evidence_preserves_exact_path_workload_and_failure_domain():
    from lead_engine.compute_fabric_telemetry import predict_failure_degradation_evidence
    samples = [
        {"observed_at": 1.0, "latency_ms": 2.0, "success": True, "evidence": {"fabric_path_id": "path-a", "workload_key": "work-a", "failure_domain": "fabric:ib0"}},
        {"observed_at": 2.0, "latency_ms": 3.0, "success": True, "evidence": {"fabric_path_id": "path-a", "workload_key": "work-a", "failure_domain": "fabric:ib0"}},
        {"observed_at": 3.0, "latency_ms": 4.0, "success": True, "evidence": {"fabric_path_id": "path-a", "workload_key": "work-a", "failure_domain": "fabric:ib0"}},
        {"observed_at": 4.0, "latency_ms": 5.0, "success": True, "evidence": {"fabric_path_id": "path-a", "workload_key": "work-a", "failure_domain": "fabric:ib0"}},
    ]
    evidence = predict_failure_degradation_evidence(samples)
    assert evidence["state"] == "degrading"
    assert evidence["failure_domains"] == ("fabric:ib0",)


def test_summarize_route_health_exposes_predictive_failure_by_workload_key_without_cross_contamination():
    from lead_engine.compute_fabric_telemetry import summarize_route_health
    summary = summarize_route_health([
        {"observed_at": 1.0, "latency_ms": 2.0, "success": True, "evidence": {"workload_key": "a", "fabric_path_id": "path-a"}},
        {"observed_at": 2.0, "latency_ms": 2.0, "success": True, "evidence": {"workload_key": "a", "fabric_path_id": "path-a"}},
        {"observed_at": 3.0, "latency_ms": 2.0, "success": False, "evidence": {"workload_key": "a", "fabric_path_id": "path-a"}},
        {"observed_at": 4.0, "latency_ms": 2.0, "success": False, "evidence": {"workload_key": "a", "fabric_path_id": "path-a"}},
        {"observed_at": 1.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "b", "fabric_path_id": "path-a"}},
        {"observed_at": 2.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "b", "fabric_path_id": "path-a"}},
        {"observed_at": 3.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "b", "fabric_path_id": "path-a"}},
        {"observed_at": 4.0, "latency_ms": 3.0, "success": True, "evidence": {"workload_key": "b", "fabric_path_id": "path-a"}},
    ])
    assert summary["predictive_failure_by_workload_key"]["a"]["state"] == "failure_pattern"
    assert summary["predictive_failure_by_workload_key"]["b"]["state"] == "stable"


def test_continuous_optimization_evidence_balances_observed_performance_and_capacity():
    from lead_engine.compute_fabric_telemetry import derive_continuous_optimization_evidence
    evidence = derive_continuous_optimization_evidence([
        {"candidate_key": "candidate-a", "observed_latency_ms": 2.0, "future_feasible_domain_count": 3, "future_single_node_count": 2, "sample_count": 8},
        {"candidate_key": "candidate-b", "observed_latency_ms": 3.0, "future_feasible_domain_count": 1, "future_single_node_count": 1, "sample_count": 8},
    ])
    assert evidence["state"] == "balanced"
    assert evidence["performance_preference"] == ("candidate-a",)
    assert evidence["capacity_preference"] == ("candidate-a",)


def test_continuous_optimization_evidence_preserves_sparse_unknowns_without_synthetic_values():
    from lead_engine.compute_fabric_telemetry import derive_continuous_optimization_evidence
    evidence = derive_continuous_optimization_evidence([
        {"candidate_key": "a"},
        {"candidate_key": "b", "future_single_node_count": 2},
    ])
    assert evidence["state"] == "capacity_preservation"
    assert evidence["performance_preference"] == ()
    assert evidence["capacity_preference"] == ("b",)
    assert "score" not in evidence
    assert "probability" not in evidence


def test_continuous_optimization_evidence_is_deterministic_and_does_not_cross_candidate_keys():
    from lead_engine.compute_fabric_telemetry import derive_continuous_optimization_evidence
    evidence = derive_continuous_optimization_evidence([
        {"candidate_key": "z", "observed_latency_ms": 2.0, "future_feasible_domain_count": 1},
        {"candidate_key": "a", "observed_latency_ms": 2.0, "future_feasible_domain_count": 1},
        {"candidate_key": "other-workload", "observed_latency_ms": 1.0, "future_feasible_domain_count": 0},
    ])
    assert evidence["performance_preference"] == ("other-workload",)
    assert evidence["capacity_preference"] == ("a", "z")
    assert evidence["balanced_preference"] == ()
