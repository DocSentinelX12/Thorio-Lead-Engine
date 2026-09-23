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
        "failure_rate": 0.0,
    }
    assert summarize_route_health([{"observed_at": 1.0, "latency_ms": 2.0, "success": "yes"}]) == {
        "sample_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "failure_rate": 0.0,
    }
