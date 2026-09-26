from __future__ import annotations
import tempfile
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.healing_authorities import HealingAuthorityGateway
from lead_engine.healing_fault_injection import HealingFaultInjection
from lead_engine.recovery_orchestrator import RecoveryOrchestrator
from lead_engine.continuous_recovery import ContinuousRecoveryController
from lead_engine.self_coordinating_fabric import FabricCoordinator

def test_fault_catalog_is_explicit_and_controller_backed():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        i=ComputeInventory(db_path=f.name); g=HealingAuthorityGateway(inventory=i,recovery_orchestrator=RecoveryOrchestrator(i),fabric_coordinator=FabricCoordinator(f.name + ".coord")); c=ContinuousRecoveryController(gateway=g,db_path=f.name); c.start(generation=1,now=1)
        names={x["name"] for x in HealingFaultInjection(c).scenario_catalog()}
        assert names=={"isolated_failure","independent_failures","controller_restart","verification_failure","protected_capacity"}

def test_fault_injection_rejects_unknown_exact_path():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        i=ComputeInventory(db_path=f.name); g=HealingAuthorityGateway(inventory=i,recovery_orchestrator=RecoveryOrchestrator(i)); c=ContinuousRecoveryController(gateway=g,db_path=f.name); c.start(generation=1,now=1)
        try: HealingFaultInjection(c).observe_failure(path_id="unknown",generation=1,fingerprint="x",criticality=2,confidence=.9,cascade_risk=.1,now=2)
        except Exception as exc: assert "unknown physical fabric path" in str(exc)
        else: raise AssertionError("unknown path was accepted")
