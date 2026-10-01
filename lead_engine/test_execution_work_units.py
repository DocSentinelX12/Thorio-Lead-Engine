from lead_engine.execution_work_units import (
    build_independent_work_units,
    WorkUnit,
)
from lead_engine.execution_fabric_contract import ExecutionMode


def test_build_independent_work_units_preserves_order_and_identity():
    units = build_independent_work_units(
        workload_id="batch-1",
        items=("a", "b", "c"),
        mode=ExecutionMode.BATCH_PARALLEL,
    )
    assert units == (
        WorkUnit("batch-1:0", "batch-1", 0, "a", ExecutionMode.BATCH_PARALLEL),
        WorkUnit("batch-1:1", "batch-1", 1, "b", ExecutionMode.BATCH_PARALLEL),
        WorkUnit("batch-1:2", "batch-1", 2, "c", ExecutionMode.BATCH_PARALLEL),
    )


def test_build_independent_work_units_rejects_multi_stage_modes():
    try:
        build_independent_work_units(
            workload_id="job-1",
            items=("a",),
            mode=ExecutionMode.PIPELINE_PARALLEL,
        )
    except ValueError as exc:
        assert "independent work-unit" in str(exc)
    else:
        raise AssertionError("expected pipeline mode rejection")


def test_build_independent_work_units_rejects_empty_input():
    try:
        build_independent_work_units(
            workload_id="job-1",
            items=(),
            mode=ExecutionMode.DATA_PARALLEL,
        )
    except ValueError as exc:
        assert "at least one item" in str(exc)
    else:
        raise AssertionError("expected empty-input rejection")
