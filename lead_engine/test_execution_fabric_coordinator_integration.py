from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.execution_fabric_contract import ExecutionMode


def test_coordinator_durably_materializes_independent_gpu_work_units(tmp_path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
    )
    task_ids = coordinator.enqueue_gpu_work_units(
        workload_id="gpu-batch",
        items=({"x": 1}, {"x": 2}),
        mode=ExecutionMode.BATCH_PARALLEL,
        command=("python", "-m", "worker_task"),
    )
    assert task_ids == ("gpu-batch:0", "gpu-batch:1")
    first = coordinator.task(task_ids[0])
    assert first["payload"]["execution_mode"] == "batch_parallel"
    assert first["payload"]["work_unit_id"] == "gpu-batch:0"
