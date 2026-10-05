from lead_engine.execution_fabric_contract import ExecutionMode
from lead_engine.parallel_grouping import ParallelGroupPlan, ParallelRank
from lead_engine.parallel_execution_spec import ParallelLaunchPlanner


def test_parallel_launch_metadata_has_deterministic_ranks():
    group = ParallelGroupPlan("p", ExecutionMode.TENSOR_PARALLEL,
        (ParallelRank(0, "n0", "g0"), ParallelRank(1, "n1", "g1")), "nccl")
    spec = ParallelLaunchPlanner().build(group, master_addr="10.0.0.1")
    assert spec.world_size == 2
    assert spec.ranks == (0, 1)
    assert dict(ParallelLaunchPlanner.rank_environment(spec, 1))["RANK"] == "1"


def test_parallel_launch_rejects_unknown_rank():
    group = ParallelGroupPlan("p", ExecutionMode.TENSOR_PARALLEL,
        (ParallelRank(0, "n0", "g0"), ParallelRank(1, "n1", "g1")), "nccl")
    spec = ParallelLaunchPlanner().build(group, master_addr="10.0.0.1")
    try:
        ParallelLaunchPlanner.rank_environment(spec, 2)
    except ValueError as exc:
        assert "not part" in str(exc)
    else:
        raise AssertionError("expected ValueError")
