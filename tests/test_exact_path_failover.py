from __future__ import annotations

from lead_engine.physical_fabric import AdaptiveFabricRouteSelector


def _path(path_id: str, nic: str, rdma: str, fabric: str) -> dict[str, object]:
    return {
        "path_id": path_id, "source_gpu": "gpu:src", "destination_gpu": "gpu:dst", "state": "MEASURED",
        "segments": ("gpu:src", nic, rdma, f"{rdma}:1", fabric, f"rdma:{fabric}:dst", "rdma:dst", "nic:dst", "gpu:dst"),
        "fabric_domains": (fabric,), "measurement": {"bandwidth_gbps": 100.0, "latency_us": 5.0},
    }


def _independent_standby(path_id: str = "standby", fabric: str = "fabric:ib2") -> dict[str, object]:
    path = _path(path_id, "nic:src-2", "rdma:src-2", fabric)
    path["segments"] = (
        "gpu:src", "nic:src-2", "rdma:src-2", "rdma:src-2:1",
        fabric, f"rdma:{fabric}:dst-2", "rdma:dst-2", "nic:dst-2", "gpu:dst",
    )
    return path


def test_exact_path_failure_activates_only_an_independent_measured_standby() -> None:
    current = _path("current", "nic:src", "rdma:src", "fabric:ib0")
    shared = _path("shared", "nic:src", "rdma:src", "fabric:ib1")
    standby = _independent_standby()
    health = {"current": {"sample_count": 10, "failure_rate": 1.0, "latency_delta_from_mean_ms": 20.0, "latest_latency_ms": 50.0}, "shared": {"sample_count": 10, "failure_rate": 0.0, "latency_delta_from_mean_ms": -10.0, "latest_latency_ms": 1.0}, "standby": {"sample_count": 10, "failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 4.0}}
    decision = AdaptiveFabricRouteSelector.failover_after_exact_path_failure([current, shared, standby], health, failed_path_id="current", gpu_pair=("gpu:src", "gpu:dst"))
    assert decision == {"migrate": True, "from_path_id": "current", "to_path_id": "standby", "reason": "exact_path_failure_independent_standby"}


def test_exact_path_failure_does_not_fail_over_without_independence_evidence() -> None:
    current = _path("current", "nic:src", "rdma:src", "fabric:ib0")
    unknown = _independent_standby("unknown", "fabric:ib1")
    unknown.pop("fabric_domains")
    health = {"current": {"sample_count": 10, "failure_rate": 1.0, "latency_delta_from_mean_ms": 20.0, "latest_latency_ms": 50.0}, "unknown": {"sample_count": 10, "failure_rate": 0.0, "latency_delta_from_mean_ms": -10.0, "latest_latency_ms": 1.0}}
    decision = AdaptiveFabricRouteSelector.failover_after_exact_path_failure([current, unknown], health, failed_path_id="current", gpu_pair=("gpu:src", "gpu:dst"))
    assert decision == {"migrate": False, "from_path_id": "current", "to_path_id": None, "reason": "no_independently_verified_standby"}


def test_exact_path_failure_recovery_preserves_generation_placement_and_attempt_identity() -> None:
    current = _path("current", "nic:src", "rdma:src", "fabric:ib0")
    standby = _independent_standby()
    health = {"current": {"sample_count": 10, "failure_rate": 1.0, "latency_delta_from_mean_ms": 20.0, "latest_latency_ms": 50.0}, "standby": {"sample_count": 10, "failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 4.0}}
    recovery = AdaptiveFabricRouteSelector.orchestrate_exact_path_recovery([current, standby], health, failed_path_id="current", gpu_pair=("gpu:src", "gpu:dst"), attempt_id="attempt-7", placement_id="placement-4", generation=9)
    assert recovery == {"migrate": True, "from_path_id": "current", "to_path_id": "standby", "reason": "exact_path_failure_independent_standby", "attempt_id": "attempt-7", "placement_id": "placement-4", "generation": 9}
