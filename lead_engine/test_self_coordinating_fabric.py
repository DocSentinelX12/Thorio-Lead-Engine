from __future__ import annotations

from .self_coordinating_fabric import FabricCoordinator, NodeCapacity, PlacementCandidate
from .compute_inventory import ComputeInventory
from .physical_fabric import FabricPathState, PhysicalFabricPath


def _coordinator(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "physical-inventory.sqlite3"))
    for path_id in ("p1", "p2", "p3", "p4", "verified-path-1"):
        inventory.persist_physical_path(
            PhysicalFabricPath(
                path_id=path_id,
                source_gpu=f"gpu:{path_id}:source",
                destination_gpu=f"gpu:{path_id}:destination",
                segments=(f"gpu:{path_id}:source", f"rdma:{path_id}:1"),
                fabric_domains=(f"domain:{path_id}",),
                state=FabricPathState.VERIFIED,
            )
        )
    coordinator = FabricCoordinator(str(tmp_path / "fabric-coordinator.sqlite3"), standby_capacity=1)
    coordinator.bind_physical_path_authority(inventory)
    return coordinator


def _candidate(workload, node, domain, path, score=1.0, *, independent=True):
    return PlacementCandidate(workload, node, domain, path, score, independent)


def test_global_allocator_handles_competing_workloads_without_double_booking(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.register_node(NodeCapacity("n2", "d2", 8, 4, 1))
    c.submit_workload("w1", criticality=2)
    c.submit_workload("w2", criticality=2)
    result = c.coordinate([
        _candidate("w1", "n1", "d1", "p1", 10), _candidate("w1", "n2", "d2", "p2", 9),
        _candidate("w2", "n1", "d1", "p3", 10), _candidate("w2", "n2", "d2", "p4", 9)])
    assert {x["workload_id"] for x in result["allocations"]} == {"w1", "w2"}
    assert {x["node_id"] for x in result["allocations"]} == {"n1", "n2"}


def test_standby_capacity_is_reserved_and_not_consumed_by_normal_allocation(tmp_path):
    c = _coordinator(tmp_path)
    for node, domain in (("n1", "d1"), ("n2", "d2"), ("n3", "d3")):
        c.register_node(NodeCapacity(node, domain, 8, 4, 1))
    c.submit_workload("w1", criticality=3)
    c.submit_workload("w2", criticality=3)
    result = c.coordinate([_candidate("w1", "n1", "d1", "p1", 10), _candidate("w2", "n2", "d2", "p2", 10)])
    assert result["standby_node_ids"] == ["n3"]


def test_failure_releases_failed_node_and_reconciles_to_independent_candidate(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.register_node(NodeCapacity("n2", "d2", 8, 4, 1))
    c.submit_workload("w1", criticality=3)
    c.coordinate([_candidate("w1", "n1", "d1", "p1", 10), _candidate("w1", "n2", "d2", "p2", 9)])
    result = c.reconcile_node_failure("n1", candidates=[_candidate("w1", "n2", "d2", "p2", 9)])
    assert result["migrated"][0]["node_id"] == "n2"
    assert result["failed_node_id"] == "n1"


def test_recovery_is_idempotent_and_does_not_reuse_failed_node(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.register_node(NodeCapacity("n2", "d2", 8, 4, 1))
    c.submit_workload("w1", criticality=3)
    c.coordinate([_candidate("w1", "n1", "d1", "p1", 10), _candidate("w1", "n2", "d2", "p2", 9)])
    first = c.reconcile_node_failure("n1", candidates=[_candidate("w1", "n2", "d2", "p2", 9)])
    second = c.reconcile_node_failure("n1", candidates=[_candidate("w1", "n2", "d2", "p2", 9)])
    assert first == second


def test_physical_path_is_consumed_but_never_invented(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.submit_workload("w1", criticality=1)
    result = c.coordinate([_candidate("w1", "n1", "d1", "verified-path-1", 10)])
    assert result["allocations"][0]["fabric_path_id"] == "verified-path-1"
    try:
        c.coordinate([PlacementCandidate("w1", "n1", "d1", "", 10, True)])
    except ValueError as exc:
        assert "fabric_path_id" in str(exc)
    else:
        raise AssertionError("missing exact physical path was accepted")


def test_control_plane_checkpoint_survives_restart(tmp_path):
    path = str(tmp_path / "fabric.sqlite3")
    c = FabricCoordinator(path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.submit_workload("w1", criticality=2)
    c.coordinate([_candidate("w1", "n1", "d1", "p1", 5)])
    restored = FabricCoordinator(path)
    assert restored.snapshot()["allocations"][0]["workload_id"] == "w1"


def test_experiment_budget_preserves_standby_reserve(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.register_node(NodeCapacity("n2", "d2", 8, 4, 1))
    assert c.can_experiment(required_nodes=1) is False
    c.submit_workload("w1", criticality=3)
    c.coordinate([_candidate("w1", "n1", "d1", "p1", 10)])
    assert c.can_experiment(required_nodes=1) is False


def test_global_decision_is_deterministic_for_equal_candidates(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("b", "d2", 8, 4, 1))
    c.register_node(NodeCapacity("a", "d1", 8, 4, 1))
    c.submit_workload("w", criticality=1)
    result = c.coordinate([_candidate("w", "b", "d2", "p2", 5), _candidate("w", "a", "d1", "p1", 5)])
    assert result["allocations"][0]["node_id"] == "a"


def test_partial_capacity_failure_preserves_other_workloads(tmp_path):
    c = _coordinator(tmp_path)
    c.register_node(NodeCapacity("n1", "d1", 8, 4, 1))
    c.register_node(NodeCapacity("n2", "d2", 8, 4, 1))
    c.submit_workload("w1", criticality=3)
    c.submit_workload("w2", criticality=1)
    c.coordinate([_candidate("w1", "n1", "d1", "p1", 10), _candidate("w2", "n2", "d2", "p2", 9)])
    result = c.reconcile_node_failure("n1", candidates=[])
    assert result["unplaced_workload_ids"] == ["w1"]
    assert c.snapshot()["allocations"][0]["workload_id"] == "w2"
