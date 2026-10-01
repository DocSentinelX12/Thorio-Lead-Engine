from lead_engine.execution_fabric_contract import ExecutionCapability, ExecutionMode, ExecutionPlan
from lead_engine.parallel_grouping import ParallelGroupPlanner


def _plan():
    return ExecutionPlan(
        plan_id="p1", workload_id="w", mode=ExecutionMode.TENSOR_PARALLEL,
        provider_id="prov", domain_id="dom", resource_ids=("g0","g1"),
        node_ids=("n0","n1"), worker_count=2,
    )


def _caps(backends=("nccl",)):
    return (
        ExecutionCapability(("g0",), ("n0",), "prov", "dom", (ExecutionMode.TENSOR_PARALLEL,), True, backends=backends, trusted=True),
        ExecutionCapability(("g1",), ("n1",), "prov", "dom", (ExecutionMode.TENSOR_PARALLEL,), True, backends=backends, trusted=True),
    )


def test_tightly_coupled_group_assigns_contiguous_ranks():
    result = ParallelGroupPlanner().plan(_plan(), _caps())
    assert [rank.rank for rank in result.ranks] == [0, 1]
    assert result.collective_backend == "nccl"


def test_group_rejects_node_without_nccl():
    try:
        ParallelGroupPlanner().plan(_plan(), _caps(("gloo",)))
    except ValueError as exc:
        assert "NCCL" in str(exc)
    else:
        raise AssertionError("expected ValueError")
