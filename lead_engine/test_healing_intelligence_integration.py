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