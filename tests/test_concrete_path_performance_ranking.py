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



def test_predictive_route_evidence_is_a_preference_after_existing_route_health():
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass
    from lead_engine.compute_fabric_telemetry import workload_performance_key

    paths = (
        {
            "path_id": "improving-path",
            "node_id": "node-a",
            "gpu_uuid": "gpu:u0",
            "nic": "nic0",
            "nic_pci_bus_id": "0000:01:00.0",
            "rdma_device": "rdma0",
            "rdma_port": 1,
            "rdma_pci_bus_id": "0000:02:00.0",
            "link_layer": "infiniband",
        },
        {
            "path_id": "degrading-path",
            "node_id": "node-a",
            "gpu_uuid": "gpu:u0",
            "nic": "nic1",
            "nic_pci_bus_id": "0000:03:00.0",
            "rdma_device": "rdma1",
            "rdma_port": 1,
            "rdma_pci_bus_id": "0000:04:00.0",
            "link_layer": "infiniband",
        },
    )
    requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        performance_signature=(("message_size_bytes", 1024),),
    )
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = requirements
    evaluator.physical_paths = paths
    evaluator.route_health = {
        "improving-path": {"sample_count": 4, "failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 4.0},
        "degrading-path": {"sample_count": 4, "failure_rate": 0.0, "latency_delta_from_mean_ms": 1.0, "latest_latency_ms": 4.0},
    }

    workload = {"workload_class": "gpu_required", "message_size_bytes": 1024}
    improving_key = workload_performance_key(paths[0], workload)
    degrading_key = workload_performance_key(paths[1], workload)
    evaluator.route_health["improving-path"]["predictive_by_workload_key"] = {
        improving_key: {"state": "improving"}
    }
    evaluator.route_health["degrading-path"]["predictive_by_workload_key"] = {
        degrading_key: {"state": "degrading"}
    }

    candidate = (
        {"node_id": "node-a", "payload_json": json.dumps({"gpu_uuid": "gpu:u0"}), "resource_key": "gpu-a"},
    )
    evaluator._adaptive_route_selection = lambda _candidate: (
        {"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "path_id": "improving-path"},
    )
    assert evaluator._candidate_predictive_route(candidate) == (0,)


def test_predictive_route_without_evidence_remains_neutral():
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass

    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = ComputeRequirements(workload_class=WorkloadClass.GPU_REQUIRED)
    evaluator.physical_paths = ()
    evaluator.route_health = {}
    evaluator._adaptive_route_selection = lambda _candidate: ()
    assert evaluator._candidate_predictive_route(()) == (1,)


def test_multidimensional_workload_preference_uses_exact_observed_combination_and_path():
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass
    from lead_engine.compute_fabric_telemetry import workload_performance_key

    paths = (
        {
            "path_id": "observed-path",
            "node_id": "node-a",
            "gpu_uuid": "gpu:u0",
            "nic": "nic0",
            "nic_pci_bus_id": "0000:01:00.0",
            "rdma_device": "rdma0",
            "rdma_port": 1,
            "rdma_pci_bus_id": "0000:02:00.0",
            "link_layer": "infiniband",
        },
        {
            "path_id": "unobserved-path",
            "node_id": "node-b",
            "gpu_uuid": "gpu:u1",
            "nic": "nic1",
            "nic_pci_bus_id": "0000:03:00.0",
            "rdma_device": "rdma1",
            "rdma_port": 1,
            "rdma_pci_bus_id": "0000:04:00.0",
            "link_layer": "infiniband",
        },
    )
    requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        performance_signature=(
            ("collective", "all_reduce"),
            ("world_size", 8),
            ("message_size_bytes", 4096),
            ("dtype", "fp16"),
        ),
    )
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = requirements
    evaluator.physical_paths = paths
    workload = {
        "workload_class": "gpu_required",
        "collective": "all_reduce",
        "world_size": 8,
        "message_size_bytes": 4096,
        "dtype": "fp16",
    }
    observed_key = workload_performance_key(paths[0], workload)
    evaluator.route_health = {
        "observed-path": {
            "multidimensional_by_workload_key": {
                observed_key: {
                    "workload_key": observed_key,
                    "sample_count": 7,
                    "dimensions": workload,
                    "observations": (
                        {"observed_at": 100.0, "latency_ms": 2.0, "success": True},
                    ),
                }
            }
        }
    }
    evaluator._adaptive_route_selection = lambda _candidate: (
        {"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "path_id": "observed-path"},
    )

    assert evaluator._candidate_multidimensional_workload((
        {"node_id": "node-a", "payload_json": json.dumps({"gpu_uuid": "gpu:u0"}), "resource_key": "gpu-a"},
    )) == (0, -7, ("observed-path",))


def test_multidimensional_workload_preference_does_not_cross_message_size_or_collective():
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass

    path = {
        "path_id": "path-1",
        "node_id": "node-a",
        "gpu_uuid": "gpu:u0",
        "nic": "nic0",
        "nic_pci_bus_id": "0000:01:00.0",
        "rdma_device": "rdma0",
        "rdma_port": 1,
        "rdma_pci_bus_id": "0000:02:00.0",
        "link_layer": "infiniband",
    }
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        performance_signature=(
            ("collective", "all_reduce"),
            ("world_size", 8),
            ("message_size_bytes", 4096),
        ),
    )
    evaluator.physical_paths = (path,)
    evaluator.route_health = {
        "path-1": {
            "multidimensional_by_workload_key": {
                "different": {
                    "workload_key": "different",
                    "sample_count": 100,
                    "dimensions": {
                        "collective": "all_gather",
                        "world_size": 8,
                        "message_size_bytes": 16384,
                    },
                    "observations": (),
                }
            }
        }
    }
    evaluator._adaptive_route_selection = lambda _candidate: (
        {"source_gpu": "gpu:u0", "destination_gpu": "gpu:u1", "path_id": "path-1"},
    )

    assert evaluator._candidate_multidimensional_workload((
        {"node_id": "node-a", "payload_json": json.dumps({"gpu_uuid": "gpu:u0"}), "resource_key": "gpu-a"},
    )) == (1, 0, ())


def test_multidimensional_workload_evidence_is_subordinate_to_predictive_route_and_existing_performance():
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass

    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = ComputeRequirements(workload_class=WorkloadClass.GPU_REQUIRED)
    evaluator.physical_paths = ()
    evaluator.route_health = {}
    evaluator._adaptive_route_selection = lambda _candidate: ()

    assert evaluator._candidate_multidimensional_workload(()) == (1, 0, ())


def test_predictive_failure_degradation_prefers_stable_exact_workload_path():
    from lead_engine.compute_placement import PlacementEvaluator
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass
    from lead_engine.compute_fabric_telemetry import workload_performance_key

    paths = (
        {"path_id": "stable-path", "node_id": "node-a", "gpu_uuid": "u0", "nic": "n0", "nic_pci_bus_id": "1",
         "rdma_device": "r0", "rdma_port": 1, "rdma_pci_bus_id": "2", "link_layer": "ib"},
        {"path_id": "degrading-path", "node_id": "node-b", "gpu_uuid": "u1", "nic": "n1", "nic_pci_bus_id": "3",
         "rdma_device": "r1", "rdma_port": 1, "rdma_pci_bus_id": "4", "link_layer": "ib"},
    )
    requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        performance_signature=(("collective", "all_reduce"), ("world_size", 8), ("message_size_bytes", 4096)),
    )
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = requirements
    evaluator.physical_paths = paths
    evaluator.route_health = {}
    workload = {"workload_class": "gpu_required", "collective": "all_reduce", "world_size": 8, "message_size_bytes": 4096}
    stable_key = workload_performance_key(paths[0], workload)
    degrading_key = workload_performance_key(paths[1], workload)
    evaluator.route_health = {
        "stable-path": {
            "predictive_failure_by_workload_key": {
                stable_key: {"state": "stable", "sample_count": 8, "failure_count": 0,
                             "consecutive_failures": 0, "evidence": {"observations": ()}}
            }
        },
        "degrading-path": {
            "predictive_failure_by_workload_key": {
                degrading_key: {"state": "degrading", "sample_count": 8, "failure_count": 1,
                                 "consecutive_failures": 0, "evidence": {"observations": ()}}
            }
        },
    }
    evaluator._adaptive_route_selection = lambda candidate: (
        {"path_id": "stable-path"} if candidate[0]["resource_key"] == "stable" else {"path_id": "degrading-path"},
    )

    stable_candidate = ({"resource_key": "stable"},)
    degrading_candidate = ({"resource_key": "degrading"},)

    assert evaluator._candidate_predictive_failure(stable_candidate)[0] == 0
    assert evaluator._candidate_predictive_failure(degrading_candidate)[0] == 2


def test_predictive_failure_degradation_does_not_cross_workload_or_path_boundaries():
    from lead_engine.compute_placement import PlacementEvaluator
    from lead_engine.compute_resources import ComputeRequirements, WorkloadClass
    from lead_engine.compute_fabric_telemetry import workload_performance_key

    path = {"path_id": "path-a", "node_id": "node-a", "gpu_uuid": "u0", "nic": "n0", "nic_pci_bus_id": "1",
            "rdma_device": "r0", "rdma_port": 1, "rdma_pci_bus_id": "2", "link_layer": "ib"}
    other = {"path_id": "path-b", "node_id": "node-b", "gpu_uuid": "u1", "nic": "n1", "nic_pci_bus_id": "3",
             "rdma_device": "r1", "rdma_port": 1, "rdma_pci_bus_id": "4", "link_layer": "ib"}
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        performance_signature=(("collective", "all_reduce"), ("world_size", 8), ("message_size_bytes", 4096)),
    )
    evaluator.physical_paths = (path, other)
    wrong_workload = workload_performance_key(path, {"workload_class": "gpu_required", "collective": "all_gather", "world_size": 8, "message_size_bytes": 4096})
    evaluator.route_health = {
        "path-a": {"predictive_failure_by_workload_key": {wrong_workload: {"state": "failure_pattern", "sample_count": 100}}},
    }
    evaluator._adaptive_route_selection = lambda _candidate: ({"path_id": "path-a"},)

    assert evaluator._candidate_predictive_failure(({"resource_key": "gpu-a"},)) == (1, 0, ())


def test_predictive_failure_degradation_never_replaces_hard_candidate_validation():
    from lead_engine.compute_placement import PlacementEvaluator

    evaluator = object.__new__(PlacementEvaluator)
    evaluator.requirements = type("Requirements", (), {})()
    evaluator.physical_paths = ()
    evaluator.route_health = {}
    evaluator._adaptive_route_selection = lambda _candidate: ()
    assert evaluator._candidate_predictive_failure(()) == (1, 0, ())
