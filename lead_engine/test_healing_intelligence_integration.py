from lead_engine.compute_inventory import ComputeInventory
from lead_engine.healing_authorities import HealingIntegrationFabric
from lead_engine.healing_closure import HealingClosureValidator
from lead_engine.healing_control_plane import ControlPlaneRecovery
from lead_engine.healing_learning import HealingLearning
from lead_engine.healing_workloads import WorkloadRecoveryPlanner
from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath
from lead_engine.recovery_orchestrator import RecoveryOrchestrator
from lead_engine.self_coordinating_fabric import FabricCoordinator


def test_integration_fabric_exposes_connected_evidence_and_intelligence(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="path-connected", source_gpu="gpu:path-connected:a",
        destination_gpu="gpu:path-connected:b",
        segments=("gpu:path-connected:a", "rdma:path-connected:1"),
        fabric_domains=("domain:path-connected",), state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    orchestrator = RecoveryOrchestrator(inventory)
    integration = HealingIntegrationFabric(
        inventory=inventory, recovery_orchestrator=orchestrator,
        fabric_coordinator=FabricCoordinator(str(tmp_path / "coord.sqlite3")),
        workload_recovery=WorkloadRecoveryPlanner(),
        control_plane=ControlPlaneRecovery(str(tmp_path / "control.sqlite3")),
        learning=HealingLearning(str(tmp_path / "learning.sqlite3")),
        closure=HealingClosureValidator(),
    )
    evidence = integration.path_evidence(path.path_id)
    assert evidence["evidence"]["path_ids"] == (path.path_id,)
    assert integration.intelligence.graph is integration.evidence_graph
    assert integration.dependencies.graph is integration.evidence_graph

def test_coordinate_writes_authoritative_allocation_relationships(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = PhysicalFabricPath(
        path_id="path-allocation", source_gpu="gpu:path-allocation:a",
        destination_gpu="gpu:path-allocation:b",
        segments=("gpu:path-allocation:a", "rdma:path-allocation:1"),
        fabric_domains=("domain:path-allocation",), state=FabricPathState.VERIFIED,
    )
    inventory.persist_physical_path(path)
    coordinator = FabricCoordinator(str(tmp_path / "coord.sqlite3"), standby_capacity=1)
    from lead_engine.self_coordinating_fabric import NodeCapacity, PlacementCandidate
    coordinator.register_node(NodeCapacity("node-a", "domain-a", 4, 4, 4))
    coordinator.submit_workload("workload-a", criticality=3)
    integration = HealingIntegrationFabric(
        inventory=inventory, recovery_orchestrator=RecoveryOrchestrator(inventory),
        fabric_coordinator=coordinator, workload_recovery=WorkloadRecoveryPlanner(),
        control_plane=ControlPlaneRecovery(str(tmp_path / "control.sqlite3")),
        learning=HealingLearning(str(tmp_path / "learning.sqlite3")),
        closure=HealingClosureValidator(),
    )
    result = integration.coordinate((PlacementCandidate("workload-a", "node-a", "domain-a", path.path_id, 10.0),))
    assert result["allocations"][0]["fabric_path_id"] == path.path_id
    relationships = integration.evidence_graph.relationships(scope_id=path.path_id)
    assert {(row["relation"], row["target_id"]) for row in relationships} >= {
        ("supports", "workload-a"), ("allocated_to", "node-a")
    }
