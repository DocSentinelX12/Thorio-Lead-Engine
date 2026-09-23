from __future__ import annotations

import pytest

from lead_engine.physical_fabric import (
    FabricPathState,
    FabricVerificationResult,
    PhysicalFabricPathBuilder,
    PhysicalFabricVerification,
)


def _components() -> list[dict[str, object]]:
    return [
        {"component_type": "gpu", "identity": "gpu:src", "node_id": "node-a"},
        {"component_type": "pci", "identity": "pci:src", "node_id": "node-a"},
        {"component_type": "numa", "identity": "numa:src", "node_id": "node-a"},
        {"component_type": "nic", "identity": "nic:src", "node_id": "node-a"},
        {"component_type": "rdma_device", "identity": "rdma:src", "node_id": "node-a"},
        {"component_type": "rdma_port", "identity": "rdma:src:1", "node_id": "node-a"},
        {"component_type": "fabric", "identity": "fabric:ib0", "node_id": "domain-1"},
        {"component_type": "rdma_port", "identity": "rdma:dst:1", "node_id": "node-b"},
        {"component_type": "rdma_device", "identity": "rdma:dst", "node_id": "node-b"},
        {"component_type": "nic", "identity": "nic:dst", "node_id": "node-b"},
        {"component_type": "numa", "identity": "numa:dst", "node_id": "node-b"},
        {"component_type": "pci", "identity": "pci:dst", "node_id": "node-b"},
        {"component_type": "gpu", "identity": "gpu:dst", "node_id": "node-b"},
    ]


def _relationships() -> list[dict[str, object]]:
    def rel(kind: str, source: str, target: str) -> dict[str, object]:
        return {
            "relationship_type": kind,
            "source": source,
            "target": target,
            "state": "known",
            "evidence": {"source": "probe"},
        }

    return [
        rel("gpu_to_pci", "gpu:src", "pci:src"),
        rel("gpu_to_numa", "gpu:src", "numa:src"),
        rel("gpu_to_nic", "gpu:src", "nic:src"),
        rel("nic_to_pci", "nic:src", "pci:src"),
        rel("nic_to_rdma_device", "nic:src", "rdma:src"),
        rel("rdma_device_to_port", "rdma:src", "rdma:src:1"),
        rel("rdma_port_to_fabric", "rdma:src:1", "fabric:ib0"),
        rel("fabric_to_rdma_port", "fabric:ib0", "rdma:dst:1"),
        rel("rdma_device_to_port", "rdma:dst", "rdma:dst:1"),
        rel("nic_to_rdma_device", "nic:dst", "rdma:dst"),
        rel("nic_to_pci", "nic:dst", "pci:dst"),
        rel("gpu_to_nic", "gpu:dst", "nic:dst"),
        rel("gpu_to_numa", "gpu:dst", "numa:dst"),
        rel("gpu_to_pci", "gpu:dst", "pci:dst"),
    ]


def test_complete_gpu_path_contains_both_locality_chains_and_fabric_domain() -> None:
    graph = {
        "components": _components(),
        "edges": _relationships(),
    }
    paths = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )

    assert len(paths) == 1
    path = paths[0]
    assert path.state is FabricPathState.CONSTRUCTED
    assert path.source_gpu == "gpu:src"
    assert path.destination_gpu == "gpu:dst"
    assert path.fabric_domains == ("fabric:ib0",)
    assert path.segments == (
        "gpu:src", "pci:src", "numa:src", "nic:src", "rdma:src",
        "rdma:src:1", "fabric:ib0", "rdma:dst:1", "rdma:dst",
        "nic:dst", "numa:dst", "pci:dst", "gpu:dst",
    )


def test_incomplete_locality_cannot_construct_a_path() -> None:
    graph = {"components": _components(), "edges": [e for e in _relationships() if e["target"] != "fabric:ib0"]}
    paths = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )
    assert paths == ()


def test_multiple_valid_paths_are_preserved_without_a_count_limit() -> None:
    relationships = _relationships()
    relationships.extend(
        [
            {"relationship_type": "gpu_to_nic", "source": "gpu:src", "target": "nic:src-2", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "nic_to_rdma_device", "source": "nic:src-2", "target": "rdma:src-2", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "rdma_device_to_port", "source": "rdma:src-2", "target": "rdma:src-2:1", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "rdma_port_to_fabric", "source": "rdma:src-2:1", "target": "fabric:ib0", "state": "known", "evidence": {"source": "probe"}},
        ]
    )
    components = _components() + [
        {"component_type": "nic", "identity": "nic:src-2", "node_id": "node-a"},
        {"component_type": "rdma_device", "identity": "rdma:src-2", "node_id": "node-a"},
        {"component_type": "rdma_port", "identity": "rdma:src-2:1", "node_id": "node-a"},
    ]
    paths = PhysicalFabricPathBuilder.build(
        locality_graph={"components": components, "edges": relationships},
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )
    assert len(paths) == 2


def test_verification_requires_exact_path_and_required_segments() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )[0]
    verification = PhysicalFabricVerification.verify(
        path,
        evidence=[
            {"segment": segment, "operation": "probe", "result": "pass"}
            for segment in path.segments
        ],
    )
    assert verification.state is FabricPathState.VERIFIED
    assert verification.path_id == path.path_id


def test_generic_endpoint_existence_cannot_verify_gpu_communication() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )[0]
    verification = PhysicalFabricVerification.verify(
        path,
        evidence=[{"operation": "endpoint_exists", "result": "pass"}],
    )
    assert verification.state is FabricPathState.CONSTRUCTED
    assert verification.reason == "required path-segment evidence is incomplete"


def test_state_progression_is_monotonic_and_recovery_retains_history() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )[0]
    verification = PhysicalFabricVerification.verify(
        path,
        evidence=[
            {"segment": segment, "operation": "probe", "result": "pass"}
            for segment in path.segments
        ],
    )
    measured = PhysicalFabricVerification.measure(
        verification,
        measurement={"bandwidth_gbps": 100, "latency_us": 4.2},
    )
    assert measured.state is FabricPathState.MEASURED
    degraded = PhysicalFabricVerification.degrade(
        measured,
        reason="rdma port error",
        failure_domain="rdma_port",
    )
    assert degraded.state is FabricPathState.DEGRADED
    recovered = PhysicalFabricVerification.recover(degraded)
    assert recovered.state is FabricPathState.RECOVERED
    assert recovered.path_id == path.path_id
    assert recovered.history
    assert recovered.history[-1]["state"] == "DEGRADED"


def test_conflicting_or_unknown_segments_are_rejected_without_guessing() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    graph["edges"] = [
        dict(edge, state="conflict")
        if edge["relationship_type"] == "gpu_to_nic" and edge["source"] == "gpu:src"
        else edge
        for edge in graph["edges"]
    ]
    assert PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    ) == ()


def test_path_construction_has_no_fixed_hardware_or_path_ceiling() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    for index in range(20):
        graph["components"].extend([
            {"component_type": "nic", "identity": f"nic:extra-{index}", "node_id": "node-a"},
            {"component_type": "rdma_device", "identity": f"rdma:extra-{index}", "node_id": "node-a"},
            {"component_type": "rdma_port", "identity": f"rdma:extra-{index}:1", "node_id": "node-a"},
        ])
        graph["edges"].extend([
            {"relationship_type": "gpu_to_nic", "source": "gpu:src", "target": f"nic:extra-{index}", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "nic_to_rdma_device", "source": f"nic:extra-{index}", "target": f"rdma:extra-{index}", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "rdma_device_to_port", "source": f"rdma:extra-{index}", "target": f"rdma:extra-{index}:1", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "rdma_port_to_fabric", "source": f"rdma:extra-{index}:1", "target": "fabric:ib0", "state": "known", "evidence": {"source": "probe"}},
        ])
    paths = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )
    assert len(paths) == 21


def test_inventory_persists_path_identity_and_verification_history(tmp_path) -> None:
    from lead_engine.compute_inventory import ComputeInventory

    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )[0]
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.persist_physical_path(path)
    verification = PhysicalFabricVerification.verify(
        path,
        evidence=[
            {"segment": segment, "operation": "probe", "result": "pass"}
            for segment in path.segments
        ],
    )
    inventory.persist_physical_verification(
        verification,
        evidence={"stage": "inter_node_collective", "operation": "probe"},
    )

    records = inventory.physical_paths()
    history = inventory.physical_verification_history()
    assert records[0]["path_id"] == path.path_id
    assert records[0]["state"] == "VERIFIED"
    assert history[0]["path_id"] == path.path_id
    assert history[0]["state"] == "VERIFIED"
    assert history[0]["evidence"]["stage"] == "inter_node_collective"


def test_failure_and_reverification_require_fresh_exact_path_evidence() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )[0]
    verified = PhysicalFabricVerification.verify(
        path,
        evidence=[
            {"segment": segment, "operation": "probe", "result": "pass"}
            for segment in path.segments
        ],
    )
    measured = PhysicalFabricVerification.measure(
        verified,
        measurement={"bandwidth_gbps": 100},
    )
    assert measured.measurement["bandwidth_gbps"] == 100

    failed = PhysicalFabricVerification.fail(
        measured,
        reason="rdma port stopped responding",
        failure_domain="rdma_port",
    )
    assert failed.state is FabricPathState.FAILED
    assert failed.failure_domain == "rdma_port"

    reverified = PhysicalFabricVerification.reverify(
        failed,
        evidence=[
            {"segment": segment, "operation": "probe", "result": "pass"}
            for segment in path.segments
        ],
    )
    assert reverified.state is FabricPathState.REVERIFIED
    assert reverified.path_id == path.path_id
    assert reverified.history[-1]["state"] == "FAILED"


def test_newer_measurement_supersedes_older_observation_and_stale_one_is_ignored():
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph, source_gpu="gpu:src", destination_gpu="gpu:dst"
    )[0]
    verified = PhysicalFabricVerification.verify(
        path,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    first = PhysicalFabricVerification.measure(
        verified, measurement={"bandwidth_gbps": 100}, observed_at=100.0
    )
    newer = PhysicalFabricVerification.measure(
        first, measurement={"bandwidth_gbps": 180}, observed_at=200.0
    )
    stale = PhysicalFabricVerification.measure(
        newer, measurement={"bandwidth_gbps": 40}, observed_at=150.0
    )
    assert newer.measurement["bandwidth_gbps"] == 180
    assert newer.measurement_observed_at == 200.0
    assert stale.measurement["bandwidth_gbps"] == 180
    assert stale.measurement_observed_at == 200.0



def test_explicit_degraded_measurement_transitions_exact_path_without_guessing() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph, source_gpu="gpu:src", destination_gpu="gpu:dst"
    )[0]
    verified = PhysicalFabricVerification.verify(
        path,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    measured = PhysicalFabricVerification.measure(
        verified,
        measurement={"bandwidth_gbps": 180, "latency_us": 4.0, "sample_count": 8},
        observed_at=100.0,
    )
    degraded = PhysicalFabricVerification.measure(
        measured,
        measurement={
            "bandwidth_gbps": 70,
            "latency_us": 12.0,
            "sample_count": 8,
            "status": "degraded",
            "degradation_reason": "measured bandwidth fell below the probe's reported capability",
            "failure_domain": "inter_node_route",
        },
        observed_at=200.0,
    )
    assert degraded.state is FabricPathState.DEGRADED
    assert degraded.path_id == path.path_id
    assert degraded.failure_domain == "inter_node_route"
    assert degraded.measurement["bandwidth_gbps"] == 70
    assert degraded.measurement_observed_at == 200.0
    assert degraded.history[-1]["state"] == "MEASURED"


def test_degraded_measurement_without_explicit_failure_metadata_does_not_guess() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph, source_gpu="gpu:src", destination_gpu="gpu:dst"
    )[0]
    verified = PhysicalFabricVerification.verify(
        path,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    measured = PhysicalFabricVerification.measure(
        verified, measurement={"bandwidth_gbps": 180}, observed_at=100.0
    )
    observed = PhysicalFabricVerification.measure(
        measured,
        measurement={"bandwidth_gbps": 70, "status": "degraded"},
        observed_at=200.0,
    )
    assert observed.state is FabricPathState.MEASURED
    assert observed.measurement["bandwidth_gbps"] == 70
    assert observed.measurement_observed_at == 200.0

def test_reverified_path_accepts_fresh_measurement_after_recovery():
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph, source_gpu="gpu:src", destination_gpu="gpu:dst"
    )[0]
    verified = PhysicalFabricVerification.verify(
        path,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    measured = PhysicalFabricVerification.measure(
        verified, measurement={"bandwidth_gbps": 100, "latency_us": 8.0, "sample_count": 4}
    )
    failed = PhysicalFabricVerification.fail(
        measured, reason="temporary fabric degradation", failure_domain="rdma_port"
    )
    reverified = PhysicalFabricVerification.reverify(
        failed,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    refreshed = PhysicalFabricVerification.measure(
        reverified, measurement={"bandwidth_gbps": 180, "latency_us": 4.0, "sample_count": 8}
    )
    assert refreshed.state is FabricPathState.MEASURED
    assert refreshed.measurement["bandwidth_gbps"] == 180
    assert refreshed.measurement["latency_us"] == 4.0
    assert refreshed.measurement["sample_count"] == 8


def test_reverification_rejects_partial_fresh_path_evidence() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph,
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )[0]
    failed = PhysicalFabricVerification.fail(
        PhysicalFabricVerification.measure(
            PhysicalFabricVerification.verify(
                path,
                evidence=[
                    {"segment": segment, "operation": "probe", "result": "pass"}
                    for segment in path.segments
                ],
            ),
            measurement={"bandwidth_gbps": 100},
        ),
        reason="temporary path failure",
        failure_domain="rdma_port",
    )
    partial = PhysicalFabricVerification.reverify(
        failed,
        evidence=[{"segment": path.segments[0], "operation": "probe", "result": "pass"}],
    )
    assert partial.state is FabricPathState.FAILED
    assert partial.reason == "fresh path-segment evidence is incomplete"


def test_competing_path_states_remain_independent_across_reload(tmp_path) -> None:
    relationships = _relationships()
    relationships.extend(
        [
            {"relationship_type": "gpu_to_nic", "source": "gpu:src", "target": "nic:src-2", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "nic_to_rdma_device", "source": "nic:src-2", "target": "rdma:src-2", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "rdma_device_to_port", "source": "rdma:src-2", "target": "rdma:src-2:1", "state": "known", "evidence": {"source": "probe"}},
            {"relationship_type": "rdma_port_to_fabric", "source": "rdma:src-2:1", "target": "fabric:ib0", "state": "known", "evidence": {"source": "probe"}},
        ]
    )
    components = _components() + [
        {"component_type": "nic", "identity": "nic:src-2", "node_id": "node-a"},
        {"component_type": "rdma_device", "identity": "rdma:src-2", "node_id": "node-a"},
        {"component_type": "rdma_port", "identity": "rdma:src-2:1", "node_id": "node-a"},
    ]
    paths = PhysicalFabricPathBuilder.build(
        locality_graph={"components": components, "edges": relationships},
        source_gpu="gpu:src",
        destination_gpu="gpu:dst",
    )
    assert len(paths) == 2

    inventory = __import__("lead_engine.compute_inventory", fromlist=["ComputeInventory"]).ComputeInventory(
        str(tmp_path / "inventory.sqlite3")
    )
    for path in paths:
        inventory.persist_physical_path(path)
        verified = PhysicalFabricVerification.verify(
            path,
            evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
        )
        inventory.persist_physical_verification(
            verified,
            evidence={"stage": "inter_node_collective", "operation": "probe"},
        )
        measured = PhysicalFabricVerification.measure(
            verified,
            measurement={"bandwidth_gbps": 200 if path.path_id == paths[0].path_id else 180, "sample_count": 8},
            observed_at=100.0,
        )
        inventory.persist_physical_verification(
            measured,
            evidence={"stage": "inter_node_collective", "operation": "measurement"},
        )

    degraded = PhysicalFabricVerification.measure(
        next(
            FabricVerificationResult(
                path_id=record["path_id"],
                state=FabricPathState(record["state"]),
                reason=record.get("reason"),
                failure_domain=record.get("failure_domain"),
                measurement=record.get("measurement") or {},
                measurement_observed_at=record.get("measurement_observed_at"),
                required_segments=tuple(record["segments"]),
            )
            for record in inventory.physical_paths()
            if record["path_id"] == paths[0].path_id
        ),
        measurement={
            "bandwidth_gbps": 60,
            "sample_count": 8,
            "status": "degraded",
            "degradation_reason": "probe reported degraded route",
            "failure_domain": "inter_node_route",
        },
        observed_at=200.0,
    )
    inventory.persist_physical_verification(
        degraded,
        evidence={"stage": "inter_node_collective", "operation": "measurement"},
    )

    reloaded = __import__("lead_engine.compute_inventory", fromlist=["ComputeInventory"]).ComputeInventory(
        str(tmp_path / "inventory.sqlite3")
    )
    records = {record["path_id"]: record for record in reloaded.physical_paths()}
    assert records[paths[0].path_id]["state"] == "DEGRADED"
    assert records[paths[1].path_id]["state"] == "MEASURED"
    assert [record["path_id"] for record in reloaded.verified_physical_paths()] == [paths[1].path_id]


def test_reverified_path_old_measurement_is_not_performance_authority_until_fresh_measurement() -> None:
    graph = {"components": _components(), "edges": _relationships()}
    path = PhysicalFabricPathBuilder.build(
        locality_graph=graph, source_gpu="gpu:src", destination_gpu="gpu:dst"
    )[0]
    verified = PhysicalFabricVerification.verify(
        path,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    measured = PhysicalFabricVerification.measure(
        verified,
        measurement={"bandwidth_gbps": 500, "latency_us": 2.0, "sample_count": 16},
        observed_at=100.0,
    )
    failed = PhysicalFabricVerification.fail(
        measured, reason="temporary route failure", failure_domain="inter_node_route"
    )
    reverified = PhysicalFabricVerification.reverify(
        failed,
        evidence=[{"segment": segment, "operation": "probe", "result": "pass"} for segment in path.segments],
    )
    assert reverified.state is FabricPathState.REVERIFIED
    assert reverified.measurement["bandwidth_gbps"] == 500

    from lead_engine.compute_placement import PlacementEvaluator

    row = {
        "resource_key": "provider/domain/node-b/gpu/gpu-dst",
        "node_id": "node-b",
        "payload_json": '{"gpu_uuid":"dst"}',
    }
    evaluator = PlacementEvaluator(
        None,
        None,
        [],
        {},
        {},
        [{
            "path_id": reverified.path_id,
            "source_gpu": "gpu:src",
            "destination_gpu": "gpu:dst",
            "state": reverified.state.value,
            "measurement": dict(reverified.measurement),
        }],
    )
    assert evaluator._candidate_concrete_performance((row,))[0] == 1

    refreshed = PhysicalFabricVerification.measure(
        reverified,
        measurement={"bandwidth_gbps": 220, "latency_us": 4.0, "sample_count": 8},
        observed_at=200.0,
    )
    assert refreshed.state is FabricPathState.MEASURED
    evaluator = PlacementEvaluator(
        None,
        None,
        [],
        {},
        {},
        [{
            "path_id": refreshed.path_id,
            "source_gpu": "gpu:src",
            "destination_gpu": "gpu:dst",
            "state": refreshed.state.value,
            "measurement": dict(refreshed.measurement),
        }],
    )
    assert evaluator._candidate_concrete_performance((row,))[0] == 1
