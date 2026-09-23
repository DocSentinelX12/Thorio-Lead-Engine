from __future__ import annotations

from lead_engine.physical_fabric import AdaptiveFabricRouteSelector


def _path(path_id: str, state: str = "MEASURED") -> dict[str, object]:
    return {
        "path_id": path_id,
        "source_gpu": "gpu:src",
        "destination_gpu": "gpu:dst",
        "state": state,
        "measurement": {"bandwidth_gbps": 100.0, "latency_us": 5.0},
    }


def test_selector_chooses_best_currently_measured_route_from_actual_health_evidence() -> None:
    paths = [_path("slow"), _path("fast")]
    health = {
        "slow": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 3.0, "latest_latency_ms": 9.0},
        "fast": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -1.0, "latest_latency_ms": 3.0},
    }
    selected = AdaptiveFabricRouteSelector.select(paths, health)
    assert selected["path_id"] == "fast"
    assert selected["selection_reason"] == "observed_route_health"
    assert selected["alternatives"] == ("slow",)


def test_selector_excludes_degraded_and_failed_routes_without_inventing_health() -> None:
    paths = [_path("degraded", "DEGRADED"), _path("failed", "FAILED"), _path("healthy")]
    health = {
        "degraded": {"sample_count": 100, "failure_rate": 0.0, "latency_delta_from_mean_ms": -100.0, "latest_latency_ms": 0.1},
        "failed": {"sample_count": 100, "failure_rate": 0.0, "latency_delta_from_mean_ms": -100.0, "latest_latency_ms": 0.1},
        "healthy": {"sample_count": 1, "failure_rate": 0.0, "latency_delta_from_mean_ms": 0.0, "latest_latency_ms": 5.0},
    }
    selected = AdaptiveFabricRouteSelector.select(paths, health)
    assert selected["path_id"] == "healthy"
    assert selected["alternatives"] == ()


def test_selector_requires_current_measured_evidence_for_performance_choice() -> None:
    paths = [_path("verified", "VERIFIED"), _path("measured", "MEASURED")]
    health = {
        "verified": {"sample_count": 100, "failure_rate": 0.0, "latency_delta_from_mean_ms": -100.0, "latest_latency_ms": 0.1},
        "measured": {"sample_count": 1, "failure_rate": 0.0, "latency_delta_from_mean_ms": 0.0, "latest_latency_ms": 5.0},
    }
    selected = AdaptiveFabricRouteSelector.select(paths, health)
    assert selected["path_id"] == "measured"


def test_migration_reselects_only_when_current_route_is_no_longer_selected() -> None:
    paths = [_path("current"), _path("alternate")]
    health = {
        "current": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 5.0, "latest_latency_ms": 10.0},
        "alternate": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -1.0, "latest_latency_ms": 3.0},
    }
    decision = AdaptiveFabricRouteSelector.migration(paths, health, current_path_id="current")
    assert decision["migrate"] is True
    assert decision["from_path_id"] == "current"
    assert decision["to_path_id"] == "alternate"
    assert decision["reason"] == "observed_route_health"


def test_migration_does_not_reselect_without_a_verified_alternative() -> None:
    paths = [_path("current", "DEGRADED")]
    health = {"current": {"sample_count": 8, "failure_rate": 1.0, "latency_delta_from_mean_ms": 5.0, "latest_latency_ms": 10.0}}
    decision = AdaptiveFabricRouteSelector.migration(paths, health, current_path_id="current")
    assert decision == {"migrate": False, "from_path_id": "current", "to_path_id": None, "reason": "no_verified_alternative"}
