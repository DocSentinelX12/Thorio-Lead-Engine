from lead_engine.compute_fabric_telemetry import extract_execution_path_observations


def test_execution_observation_closes_feedback_to_exact_concrete_path():
    verification = {
        "placement_id": "placement-1",
        "process_evidence": [{
            "rank": 0,
            "gpu_binding": {"planned_physical_path": {
                "fabric_path_id": "fabric-path-1",
                "path_id": "fabric-path-1",
            }},
            "probe": {
                "rank": 0,
                "gpu_uuid": "GPU-0",
                "all_reduce_elapsed_ms": 2.5,
                "network_transport": "IB",
            },
        }],
    }
    assert extract_execution_path_observations(verification, observed_at=300.0) == (
        {
            "fabric_path_id": "fabric-path-1",
            "latency_us": 2500.0,
            "success": True,
            "observed_at": 300.0,
            "evidence": {
                "source": "observed_all_reduce",
                "placement_id": "placement-1",
                "rank": 0,
                "gpu_uuid": "GPU-0",
                "network_transport": "IB",
            },
        },
    )


def test_execution_without_exact_path_identity_cannot_update_physical_path():
    verification = {
        "process_evidence": [{
            "rank": 0,
            "gpu_binding": {"planned_physical_path": {"node_id": "node-0"}},
            "probe": {
                "rank": 0,
                "gpu_uuid": "GPU-0",
                "all_reduce_elapsed_ms": 2.5,
            },
        }],
    }
    assert extract_execution_path_observations(verification, observed_at=300.0) == ()
}
