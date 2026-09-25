from lead_engine.active_path_intelligence import ActivePathIntelligence


def _sample(path_id, observed_at, bandwidth_gbps, *, status="measured", verified=True, worker_id="worker-a", remote_worker_id="worker-b", direction="client_to_server", remote_endpoint="198.51.100.10"):
    return {
        "path_id": path_id,
        "observed_at": observed_at,
        "measurement": {
            "measurement_status": status,
            "verified": verified,
            "bandwidth_gbps": bandwidth_gbps,
            "worker_id": worker_id,
            "remote_worker_id": remote_worker_id,
            "remote_endpoint": remote_endpoint,
            "direction": direction,
            "fabric_path_id": path_id,
        },
    }


def test_active_path_intelligence_requires_its_own_history_before_baseline():
    result = ActivePathIntelligence.analyze([
        _sample("path-1", 1.0, 100.0),
    ], path_id="path-1")

    assert result["state"] == "insufficient_evidence"
    assert result["baseline"] is None
    assert result["comparable_sample_count"] == 1
    assert result["synthetic_baseline"] is False


def test_active_path_intelligence_detects_degradation_against_same_path_history():
    result = ActivePathIntelligence.analyze([
        _sample("path-1", 1.0, 200.0),
        _sample("path-1", 2.0, 198.0),
        _sample("path-1", 3.0, 140.0),
    ], path_id="path-1")

    assert result["state"] == "degrading"
    assert result["baseline"]["sample_count"] == 2
    assert result["baseline"]["bandwidth_gbps"] == 199.0
    assert result["latest"]["bandwidth_gbps"] == 140.0
    assert result["bandwidth_delta_gbps"] == -59.0
    assert result["bandwidth_change_ratio"] < 0
    assert result["failure_or_connectivity_failure"] is False


def test_active_path_intelligence_detects_instability_without_calling_it_failure():
    result = ActivePathIntelligence.analyze([
        _sample("path-1", 1.0, 100.0),
        _sample("path-1", 2.0, 200.0),
        _sample("path-1", 3.0, 100.0),
        _sample("path-1", 4.0, 200.0),
    ], path_id="path-1")

    assert result["state"] == "unstable"
    assert result["failure_or_connectivity_failure"] is False
    assert result["variability"]["coefficient_of_variation"] > 0.10


def test_active_path_intelligence_distinguishes_connectivity_failure_from_bandwidth_degradation():
    result = ActivePathIntelligence.analyze([
        _sample("path-1", 1.0, 200.0),
        _sample("path-1", 2.0, 198.0),
        _sample("path-1", 3.0, None, status="failed", verified=False),
    ], path_id="path-1")

    assert result["state"] == "failed"
    assert result["failure_or_connectivity_failure"] is True
    assert result["bandwidth_delta_gbps"] is None
    assert result["reverification"]["required"] is True


def test_active_path_intelligence_never_merges_different_endpoint_or_direction_history():
    samples = [
        _sample("path-1", 1.0, 200.0, remote_worker_id="worker-b", direction="client_to_server"),
        _sample("path-1", 2.0, 198.0, remote_worker_id="worker-b", direction="client_to_server"),
        _sample("path-1", 3.0, 100.0, remote_worker_id="worker-c", direction="client_to_server"),
        _sample("path-1", 4.0, 100.0, remote_worker_id="worker-b", direction="server_to_client"),
    ]

    result = ActivePathIntelligence.analyze(samples, path_id="path-1")

    assert result["comparable_sample_count"] == 2
    assert result["endpoint_identity"]["remote_worker_id"] == "worker-b"
    assert result["endpoint_identity"]["direction"] == "client_to_server"


def test_active_path_intelligence_marks_measured_after_failure_as_recovery_evidence():
    result = ActivePathIntelligence.analyze([
        _sample("path-1", 1.0, None, status="failed", verified=False),
        _sample("path-1", 2.0, 190.0),
        _sample("path-1", 3.0, 192.0),
    ], path_id="path-1")

    assert result["state"] == "recovered"
    assert result["recovery"]["prior_failure_observed"] is True
    assert result["recovery"]["latest_measurement_verified"] is True
    assert result["reverification"]["required"] is True
    assert "recovered" in result["reverification"]["reason"]


def test_active_path_intelligence_rejects_mismatched_path_identity():
    result = ActivePathIntelligence.analyze([
        _sample("path-2", 1.0, 200.0),
        _sample("path-2", 2.0, 200.0),
    ], path_id="path-1")

    assert result["state"] == "insufficient_evidence"
    assert result["comparable_sample_count"] == 0


def test_adaptive_route_selector_uses_active_path_evidence_as_a_tiebreaker():
    from lead_engine.physical_fabric import AdaptiveFabricRouteSelector, FabricPathState

    paths = [
        {"path_id": "path-a", "source_gpu": "gpu:a", "destination_gpu": "gpu:b", "state": FabricPathState.MEASURED.value, "segments": ["gpu:a", "nic:a", "rdma:a"], "fabric_domains": ["fabric:a"], "measurement": {"bandwidth_gbps": 200.0}},
        {"path_id": "path-b", "source_gpu": "gpu:a", "destination_gpu": "gpu:b", "state": FabricPathState.MEASURED.value, "segments": ["gpu:a", "nic:b", "rdma:b"], "fabric_domains": ["fabric:b"], "measurement": {"bandwidth_gbps": 200.0}},
    ]
    route_health = {
        "path-a": {"failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 5.0, "sample_count": 4},
        "path-b": {"failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 5.0, "sample_count": 4},
    }
    active = {
        "path-a": {"state": "degrading", "bandwidth_change_ratio": -0.30},
        "path-b": {"state": "stable", "bandwidth_change_ratio": 0.01},
    }

    result = AdaptiveFabricRouteSelector.select(paths, route_health, active_path_intelligence=active)

    assert result["path_id"] == "path-b"
    assert result["selection_reason"] == "observed_route_health_and_active_path_evidence"
    assert result["evidence"][0]["active_path_intelligence"]["state"] == "stable"


def test_scheduler_attaches_durable_active_path_intelligence_to_canonical_paths():
    from types import SimpleNamespace
    from lead_engine.compute_scheduler import ComputeScheduler

    scheduler = object.__new__(ComputeScheduler)
    scheduler.physical_path_provider = lambda: ({"path_id": "path-1", "state": "MEASURED", "measurement": {"bandwidth_gbps": 190.0}},)
    scheduler.inventory = SimpleNamespace(
        active_path_intelligence_for_paths=lambda path_ids: {
            "path-1": {"state": "degrading", "bandwidth_change_ratio": -0.20}
        }
    )

    paths = scheduler._physical_paths()

    assert paths[0]["active_path_intelligence"]["state"] == "degrading"
    assert paths[0]["active_path_intelligence"]["bandwidth_change_ratio"] == -0.20
