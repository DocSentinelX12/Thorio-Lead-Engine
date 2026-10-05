from lead_engine.execution_fabric_contract import ExecutionMode
from lead_engine.execution_work_units import build_independent_work_units


def test_single_gpu_mode_can_be_represented_as_one_independent_unit():
    units = build_independent_work_units(
        workload_id="single-1",
        items=({"prompt": "hello"},),
        mode=ExecutionMode.SINGLE_GPU,
    )
    assert len(units) == 1
    assert units[0].mode is ExecutionMode.SINGLE_GPU
