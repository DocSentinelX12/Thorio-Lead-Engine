"""Autonomous compute-fabric closed-loop integration contracts."""

from __future__ import annotations

from lead_engine.compute_fabric import ComputeFabricController, FabricCycleReport
from lead_engine.compute_fabric_telemetry import derive_autonomous_closed_loop_evidence


def test_autonomous_closed_loop_evidence_selects_recovery_before_new_work():
    evidence = derive_autonomous_closed_loop_evidence({
        "queued_tasks": 4, "leased_tasks": 2, "eligible_resources": 16,
        "recovered_expired_tasks": 1, "requeued_tasks": 1,
        "scheduled_allocations": 0, "execution_feedback_samples": 0,
    })
    assert evidence["state"] == "recovery_and_reschedule"
    assert evidence["next_cycle_action"] == "reconcile_and_reschedule"


def test_autonomous_closed_loop_evidence_reuses_observed_feedback():
    evidence = derive_autonomous_closed_loop_evidence({
        "queued_tasks": 1, "leased_tasks": 0, "eligible_resources": 8,
        "recovered_expired_tasks": 0, "requeued_tasks": 0,
        "scheduled_allocations": 0, "execution_feedback_samples": 7,
    })
    assert evidence["state"] == "feedback_available"
    assert evidence["next_cycle_action"] == "reuse_observed_feedback"
    assert evidence["synthetic_values"] is False


def test_controller_exposes_closed_loop_evidence_without_replacing_authorities():
    class Coordinator:
        def recover_expired_tasks(self):
            return 0
        def reconcile_fabric(self):
            return {"reconciled": 0, "requeued": 0}
        def claim_physical(self):
            return None
        def fabric_closed_loop_evidence(self, *, scheduled_allocations, recovered_expired_tasks, reconciled_attempts, requeued_tasks):
            return derive_autonomous_closed_loop_evidence({
                "queued_tasks": 1, "leased_tasks": 0, "eligible_resources": 3,
                "recovered_expired_tasks": recovered_expired_tasks,
                "requeued_tasks": requeued_tasks,
                "scheduled_allocations": scheduled_allocations,
                "execution_feedback_samples": 2,
                "reconciled_attempts": reconciled_attempts,
            })

    class Inventory:
        def eligible(self, now):
            return ["resource-1", "resource-2", "resource-3"]

    class Fabric:
        inventory = Inventory()
        def refresh(self):
            return FabricCycleReport((), 3, 0)
        def continuous_optimization(self):
            return {"state": "observed"}

    report = ComputeFabricController(Coordinator(), fabric=Fabric()).cycle(max_allocations_per_cycle=1)
    assert report.closed_loop["state"] == "feedback_available"
    assert report.closed_loop["next_cycle_action"] == "reuse_observed_feedback"
    assert report.closed_loop["synthetic_values"] is False


def test_coordinator_closed_loop_reads_durable_execution_feedback(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator

    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "token")
    task_id = coordinator.enqueue({"compute_requirements": {"workload_class": "gpu_required"}})
    now = 1000.0
    with coordinator._connect() as connection:
        connection.execute(
            """INSERT INTO compute_fabric_execution_metrics(
                   metric_id,task_id,attempt_id,generation,worker_id,rank,gpu_uuid,node_id,
                   transport,all_reduce_elapsed_ms,observed_at,path_key,workload_key,placement_id,fabric_path_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("metric-1", task_id, "attempt-1", 1, "worker-1", 0, "GPU-1", "node-1",
             "IB", 2.5, now, "path-1", "workload-1", "placement-1", "fabric-path-1"),
        )
        connection.commit()

    evidence = coordinator.fabric_closed_loop_evidence()
    assert evidence["state"] == "feedback_available"
    assert evidence["execution_feedback_samples"] == 1
    assert evidence["last_feedback_observed_at"] == now
    assert evidence["feedback_is_durable"] is True
    assert evidence["queued_tasks"] == 1
    assert evidence["synthetic_values"] is False
