from __future__ import annotations

import json

from lead_engine.compute_placement import PlacementEvaluator


def _candidate(source_gpu: str, destination_gpu: str, left: str, right: str) -> tuple[dict, dict]:
    return (
        {"node_id": "node-a", "payload_json": json.dumps({"gpu_uuid": source_gpu}), "resource_key": left},
        {"node_id": "node-b", "payload_json": json.dumps({"gpu_uuid": destination_gpu}), "resource_key": right},
    )


def _evaluator(paths: tuple[dict, ...]) -> PlacementEvaluator:
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.physical_paths = paths
    return evaluator


def test_concrete_path_performance_ranking_uses_observed_measurements_only():
    evaluator = _evaluator((
        {
            "path_id": "slow-path",
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 100.0, "latency_us": 8.0, "sample_count": 10},
        },
        {
            "path_id": "fast-path",
            "source_gpu": "gpu:u2",
            "destination_gpu": "gpu:u3",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 400.0, "latency_us": 3.0, "sample_count": 20},
        },
    ))
    slow = evaluator._candidate_concrete_performance(_candidate("u0", "u1", "a", "b"))
    fast = evaluator._candidate_concrete_performance(_candidate("u2", "u3", "c", "d"))
    assert fast < slow


def test_unmeasured_concrete_path_is_ranked_after_measured_path():
    evaluator = _evaluator((
        {
            "path_id": "unmeasured-path",
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "state": "VERIFIED",
            "measurement": {},
        },
        {
            "path_id": "measured-path",
            "source_gpu": "gpu:u2",
            "destination_gpu": "gpu:u3",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 200.0, "latency_us": 5.0, "sample_count": 1},
        },
    ))
    unmeasured = evaluator._candidate_concrete_performance(_candidate("u0", "u1", "a", "b"))
    measured = evaluator._candidate_concrete_performance(_candidate("u2", "u3", "c", "d"))
    assert measured < unmeasured


def test_placement_evaluator_uses_adaptive_route_selection_for_each_gpu_pair():
    evaluator = _evaluator((
        {
            "path_id": "slow-path",
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 100.0, "latency_us": 8.0, "sample_count": 10},
        },
        {
            "path_id": "fast-path",
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 400.0, "latency_us": 3.0, "sample_count": 20},
        },
    ))
    evaluator.route_health = {
        "slow-path": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 4.0, "latest_latency_ms": 8.0},
        "fast-path": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -1.0, "latest_latency_ms": 3.0},
    }

    selected = evaluator._adaptive_route_selection(_candidate("u0", "u1", "a", "b"))

    assert selected == (
        {"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "path_id": "fast-path"},
    )


def test_candidate_route_health_uses_canonical_adaptive_route_evidence_for_cross_node_pairs():
    evaluator = _evaluator((
        {
            "path_id": "slow-path",
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 100.0, "latency_us": 8.0, "sample_count": 10},
        },
        {
            "path_id": "fast-path",
            "source_gpu": "gpu:u0",
            "destination_gpu": "gpu:u1",
            "state": "MEASURED",
            "measurement": {"bandwidth_gbps": 400.0, "latency_us": 3.0, "sample_count": 20},
        },
    ))
    evaluator.route_health = {
        "slow-path": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": 4.0, "latest_latency_ms": 8.0},
        "fast-path": {"sample_count": 8, "failure_rate": 0.0, "latency_delta_from_mean_ms": -1.0, "latest_latency_ms": 3.0},
    }
    evaluator.scheduler = type("Scheduler", (), {"_verified_gpu_nic_rdma_path": staticmethod(lambda *_args: ())})()

    assert evaluator._candidate_route_health(_candidate("u0", "u1", "a", "b")) == (0, -1.0, 0.0, 3.0, -8)
