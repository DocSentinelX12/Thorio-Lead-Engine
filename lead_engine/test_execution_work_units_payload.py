from lead_engine.execution_fabric_contract import ExecutionMode
from lead_engine.execution_work_units import WorkUnit, build_independent_work_units, build_gpu_workload_payload


def test_gpu_payload_is_physical_gpu_constrained_and_identity_bound():
    unit = WorkUnit(
        "job-1:0",
        "job-1",
        0,
        {"input": "a"},
        ExecutionMode.BATCH_PARALLEL,
    )
    payload = build_gpu_workload_payload(
        unit,
        command=("python", "-m", "worker_task", "--unit", unit.unit_id),
    )
    assert payload["kind"] == "gpu_workload"
    assert payload["workload_id"] == "job-1"
    assert payload["work_unit_id"] == "job-1:0"
    assert payload["compute_requirements"] == {
        "workload_class": "gpu_required",
        "gpu": {"gpu_count": 1},
        "same_node": True,
    }
    assert payload["command"] == [
        "python", "-m", "worker_task", "--unit", "job-1:0"
    ]


def test_gpu_payload_rejects_empty_commands():
    unit = build_independent_work_units(
        workload_id="job-1",
        items=("a",),
        mode=ExecutionMode.DATA_PARALLEL,
    )[0]
    try:
        build_gpu_workload_payload(unit, command=())
    except ValueError as exc:
        assert "command" in str(exc)
    else:
        raise AssertionError("expected empty command rejection")
