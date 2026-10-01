from lead_engine.execution_fabric_contract import ExecutionMode
from lead_engine.execution_work_units import build_independent_work_units


def test_independent_work_units_preserve_order_and_identity():
    units = build_independent_work_units(
        workload_id="job-1",
        items=("a", "b", "c"),
        mode=ExecutionMode.DATA_PARALLEL,
    )
    assert [unit.item_index for unit in units] == [0, 1, 2]
    assert [unit.unit_id for unit in units] == ["job-1:0", "job-1:1", "job-1:2"]
    assert [unit.item for unit in units] == ["a", "b", "c"]


def test_independent_work_units_reject_empty_items():
    try:
        build_independent_work_units(
            workload_id="job-1",
            items=(),
            mode=ExecutionMode.BATCH_PARALLEL,
        )
    except ValueError as exc:
        assert "at least one item" in str(exc)
    else:
        raise AssertionError("expected empty-item rejection")


def test_independent_work_units_reject_distributed_only_mode():
    try:
        build_independent_work_units(
            workload_id="job-1",
            items=("a",),
            mode=ExecutionMode.TENSOR_PARALLEL,
        )
    except ValueError as exc:
        assert "independent" in str(exc)
    else:
        raise AssertionError("expected unsupported-mode rejection")
