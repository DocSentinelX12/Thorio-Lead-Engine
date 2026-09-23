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


def test_selector_selects_best_measured_route_independently_for_each_gpu_pair() -> None:
    paths = [
        _path("u0-u1-slow"),
        _path("u0-u1-fast"),
        _path("u1-u2-fast"),
    ]
    paths[0]["source_gpu"] = "gpu:u0"
    paths[0]["destination_gpu"] = "gpu:u1"
    paths[1]["source_gpu"] = "gpu:u0"
    paths[1]["destination_gpu"] = "gpu:u1"
    paths[2]["source_gpu"] = "gpu:u1"
    paths[2]["destination_gpu"] = "gpu:u2"
    health = {
        "u0-u1-slow": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 4.0, "latest_latency_ms": 8.0},
        "u0-u1-fast": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -1.0, "latest_latency_ms": 3.0},
        "u1-u2-fast": {"sample_count": 6, "failure_rate": 0.0, "latency_delta_from_mean_ms": -2.0, "latest_latency_ms": 2.0},
    }

    selected = AdaptiveFabricRouteSelector.select_for_gpu_pairs(
        paths,
        health,
        (("gpu:u0", "gpu:u1"), ("gpu:u1", "gpu:u2")),
    )

    assert selected == (
        {"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "path_id": "u0-u1-fast"},
        {"source_gpu": "gpu:u1", "destination_gpu": "gpu:u2", "path_id": "u1-u2-fast"},
    )


def test_adaptive_replacement_plan_reselects_each_gpu_pair_from_current_route_health() -> None:
    paths = [
        _path("u0-u1-current"),
        _path("u0-u1-replacement"),
        _path("u1-u2-current"),
    ]
    paths[0]["source_gpu"], paths[0]["destination_gpu"] = "gpu:u0", "gpu:u1"
    paths[1]["source_gpu"], paths[1]["destination_gpu"] = "gpu:u0", "gpu:u1"
    paths[2]["source_gpu"], paths[2]["destination_gpu"] = "gpu:u1", "gpu:u2"
    health = {
        "u0-u1-current": {"sample_count": 8, "failure_rate": 0.8, "latency_delta_from_mean_ms": 9.0, "latest_latency_ms": 15.0},
        "u0-u1-replacement": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -1.0, "latest_latency_ms": 3.0},
        "u1-u2-current": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 0.0, "latest_latency_ms": 4.0},
    }
    plan = AdaptiveFabricRouteSelector.adaptive_replacement_plan(
        paths,
        health,
        (
            {"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "current_path_id": "u0-u1-current"},
            {"source_gpu": "gpu:u1", "destination_gpu": "gpu:u2", "current_path_id": "u1-u2-current"},
        ),
    )
    assert plan == (
        {
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "from_path_id": "u0-u1-current",
            "to_path_id": "u0-u1-replacement",
            "migrate": True,
            "reason": "observed_route_health",
        },
        {
            "source_gpu": "gpu:u1",
            "destination_gpu": "gpu:u2",
            "from_path_id": "u1-u2-current",
            "to_path_id": "u1-u2-current",
            "migrate": False,
            "reason": "current_route_remains_selected",
        },
    )


def test_cross_node_gpu_pairs_include_both_runtime_directions() -> None:
    from lead_engine.compute_placement import PlacementEvaluator

    candidate = (
        {"node_id": "node-a", "payload_json": '{"gpu_uuid":"u0"}'},
        {"node_id": "node-b", "payload_json": '{"gpu_uuid":"u1"}'},
        {"node_id": "node-c", "payload_json": '{"gpu_uuid":"u2"}'},
    )
    assert PlacementEvaluator._cross_node_gpu_pairs(candidate) == (
        ("gpu:u0", "gpu:u1"),
        ("gpu:u0", "gpu:u2"),
        ("gpu:u1", "gpu:u0"),
        ("gpu:u1", "gpu:u2"),
        ("gpu:u2", "gpu:u0"),
        ("gpu:u2", "gpu:u1"),
    )



def test_failure_domain_independence_rejects_shared_physical_components_and_requires_known_domains() -> None:
    shared_source = _path("shared-source")
    shared_source["segments"] = (
        "gpu:src", "pci:src", "numa:src", "nic:src", "rdma:src", "rdma:src:1",
        "fabric:ib0", "rdma:dst:1", "rdma:dst", "nic:dst", "gpu:dst",
    )
    shared_source["fabric_domains"] = ("fabric:ib0",)

    shared_source_alternate = dict(shared_source)
    shared_source_alternate["path_id"] = "shared-source-alternate"
    shared_source_alternate["segments"] = tuple(
        "nic:src" if segment == "nic:src-2" else segment
        for segment in (
            "gpu:src", "pci:src-2", "numa:src", "nic:src", "rdma:src", "rdma:src:2",
            "fabric:ib0", "rdma:dst:2", "rdma:dst", "nic:dst", "gpu:dst",
        )
    )
    shared_source_alternate["fabric_domains"] = ("fabric:ib0",)

    independent = _path("independent")
    independent["segments"] = (
        "gpu:src", "pci:src-2", "numa:src", "nic:src-2", "rdma:src-2", "rdma:src-2:1",
        "fabric:ib1", "rdma:dst-2:1", "rdma:dst-2", "nic:dst-2", "gpu:dst",
    )
    independent["fabric_domains"] = ("fabric:ib1",)

    assert AdaptiveFabricRouteSelector.failure_domain_independent(shared_source, shared_source_alternate) is False
    assert AdaptiveFabricRouteSelector.failure_domain_independent(shared_source, independent) is True


def test_failure_domain_independence_does_not_invent_redundancy_when_domain_data_is_missing() -> None:
    first = _path("first")
    first["segments"] = ("gpu:src", "nic:src", "rdma:src", "rdma:src:1", "rdma:dst:1", "rdma:dst", "nic:dst", "gpu:dst")
    second = dict(first)
    second["path_id"] = "second"
    second["segments"] = ("gpu:src", "nic:src-2", "rdma:src-2", "rdma:src-2:1", "rdma:dst-2:1", "rdma:dst-2", "nic:dst-2", "gpu:dst")
    first.pop("fabric_domains", None)
    second.pop("fabric_domains", None)

    assert AdaptiveFabricRouteSelector.failure_domain_independent(first, second) is False



def test_adaptive_replacement_plan_uses_only_failure_domain_independent_alternatives() -> None:
    current = _path("current")
    current["segments"] = ("gpu:src", "nic:src", "rdma:src", "rdma:src:1", "fabric:ib0", "rdma:dst:1", "rdma:dst", "nic:dst", "gpu:dst")
    current["fabric_domains"] = ("fabric:ib0",)

    shared = dict(current)
    shared["path_id"] = "shared"
    shared["segments"] = ("gpu:src", "nic:src", "rdma:src", "rdma:src:2", "fabric:ib0", "rdma:dst:2", "rdma:dst", "nic:dst", "gpu:dst")

    independent = dict(current)
    independent["path_id"] = "independent"
    independent["segments"] = ("gpu:src", "nic:src-2", "rdma:src-2", "rdma:src-2:1", "fabric:ib1", "rdma:dst-2:1", "rdma:dst-2", "nic:dst-2", "gpu:dst")
    independent["fabric_domains"] = ("fabric:ib1",)

    health = {
        "current": {"sample_count": 8, "failure_rate": 0.8, "latency_delta_from_mean_ms": 9.0, "latest_latency_ms": 15.0},
        "shared": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -2.0, "latest_latency_ms": 2.0},
        "independent": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 4.0},
    }

    plan = AdaptiveFabricRouteSelector.adaptive_replacement_plan(
        [current, shared, independent],
        health,
        ({"source_gpu": "gpu:src", "destination_gpu": "gpu:dst", "current_path_id": "current"},),
    )

    assert plan[0]["migrate"] is True
    assert plan[0]["to_path_id"] == "independent"
    assert plan[0]["reason"] == "observed_route_health"



def test_failure_domain_components_are_derived_by_component_identity_not_segment_position() -> None:
    first = _path("first")
    first["segments"] = (
        "gpu:src", "pci:src-a", "pci:src-b", "numa:src", "nic:src", "rdma:src", "rdma:src:1",
        "fabric:ib0", "rdma:dst:1", "rdma:dst", "nic:dst", "numa:dst", "pci:dst", "gpu:dst",
    )
    first["fabric_domains"] = ("fabric:ib0",)
    second = dict(first)
    second["path_id"] = "second"
    second["segments"] = (
        "gpu:src", "pci:src-x", "numa:src", "nic:src", "rdma:src-2", "rdma:src-2:1",
        "fabric:ib1", "rdma:dst-2:1", "rdma:dst-2", "nic:dst-2", "numa:dst", "pci:dst", "gpu:dst",
    )
    second["fabric_domains"] = ("fabric:ib1",)

    assert AdaptiveFabricRouteSelector.failure_domain_independent(first, second) is False
