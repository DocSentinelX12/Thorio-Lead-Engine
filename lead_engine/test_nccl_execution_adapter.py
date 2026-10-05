from lead_engine.execution_fabric_contract import ExecutionMode, ExecutionPlan
from lead_engine.nccl_execution_adapter import NCCLExecutionAdapter
from lead_engine.parallel_grouping import ParallelGroupPlanner, ParallelGroupPlan, ParallelRank


def test_launch_spec_matches_group():
    group = ParallelGroupPlan("p1", ExecutionMode.TENSOR_PARALLEL,
        (ParallelRank(0,"n0","g0"), ParallelRank(1,"n1","g1")), "nccl")
    spec = NCCLExecutionAdapter().build_launch_spec(
        group, master_addr="10.0.0.1", master_port=29501, socket_ifname="eth0")
    assert spec.world_size == 2
    assert spec.ranks == (0, 1)


def test_physical_proof_requires_distinct_observed_identity():
    records = [
        {"backend":"nccl","rank":0,"world_size":2,"nnodes":2,"collective":"all_reduce",
         "expected_sum":3,"verified_on_gpu":True,"gpu_uuid":"GPU-A","hostname":"host-a"},
        {"backend":"nccl","rank":1,"world_size":2,"nnodes":2,"collective":"all_reduce",
         "expected_sum":3,"verified_on_gpu":True,"gpu_uuid":"GPU-B","hostname":"host-b"},
    ]
    proof = NCCLExecutionAdapter().verify_physical_proof(records, proof_ref="sha")
    assert proof.ranks == (0,1)
    assert proof.proof_ref == "sha"


def test_physical_proof_rejects_duplicate_gpu():
    records = [
        {"backend":"nccl","rank":0,"world_size":2,"nnodes":2,"collective":"all_reduce",
         "expected_sum":3,"verified_on_gpu":True,"gpu_uuid":"GPU-A","hostname":"host-a"},
        {"backend":"nccl","rank":1,"world_size":2,"nnodes":2,"collective":"all_reduce",
         "expected_sum":3,"verified_on_gpu":True,"gpu_uuid":"GPU-A","hostname":"host-b"},
    ]
    try:
        NCCLExecutionAdapter().verify_physical_proof(records)
    except ValueError as exc:
        assert "distinct physical GPUs" in str(exc)
    else:
        raise AssertionError("expected ValueError")
