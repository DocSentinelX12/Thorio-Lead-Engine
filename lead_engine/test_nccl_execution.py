from lead_engine.nccl_execution import NCCLExecutionPlanner, NCCLLaunchSpec
from lead_engine.execution_fabric_contract import ExecutionMode, ExecutionPlan


def _plan():
    return ExecutionPlan(
        "nccl-plan", "nccl-workload", ExecutionMode.NCCL, "provider", "domain",
        ("gpu0", "gpu1"), ("node0", "node1"), 2,
    )


def test_nccl_launch_spec_is_deterministic_and_plan_only():
    result = NCCLExecutionPlanner().plan(
        _plan(), NCCLLaunchSpec(master_addr="10.0.0.1", master_port=29500, socket_interface="eth0")
    )
    assert result.world_size == 2
    assert result.nnodes == 2
    assert result.rank_assignments == (("0", "node0", "gpu0"), ("1", "node1", "gpu1"))
    assert result.collective == "all_reduce"
    assert result.evidence_state == "plan_only"
    assert result.physical_execution_verified is False


def test_nccl_requires_multiple_physical_nodes():
    plan = ExecutionPlan(
        "p", "w", ExecutionMode.NCCL, "provider", "domain",
        ("g0", "g1"), ("same", "same2"), 2,
    )
    try:
        NCCLExecutionPlanner().plan(plan, NCCLLaunchSpec("10.0.0.1", 29500, "eth0"))
    except ValueError as exc:
        assert "distinct physical node" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_nccl_rejects_invalid_port():
    try:
        NCCLExecutionPlanner().plan(_plan(), NCCLLaunchSpec("10.0.0.1", 0, "eth0"))
    except ValueError as exc:
        assert "port" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_nccl_rejects_missing_network_interface():
    try:
        NCCLExecutionPlanner().plan(_plan(), NCCLLaunchSpec("10.0.0.1", 29500, ""))
    except ValueError as exc:
        assert "socket interface" in str(exc)
    else:
        raise AssertionError("expected ValueError")
