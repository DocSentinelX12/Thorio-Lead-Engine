from lead_engine.execution_fabric_contract import ExecutionMode
from lead_engine.fabric_verification import FabricVerificationMatrix


def test_hybrid_requires_both_partition_and_nccl_evidence():
    report = FabricVerificationMatrix().evaluate(
        ExecutionMode.HYBRID,
        {
            "physical_gpu_execution": True,
            "execution_identity": True,
            "model_partition_plan": True,
            "nccl_physical_proof": False,
            "distinct_physical_nodes": True,
        },
    )
    assert not report.passed
    assert report.missing == ("nccl_physical_proof",)


def test_fabric_readiness_requires_external_physical_evidence():
    report = FabricVerificationMatrix().evaluate_fabric_readiness({
        "free_external_gpu_acquisition": True,
        "physical_gpu_execution": True,
        "multi_node_nccl": True,
        "twelve_domain_validation": False,
    })
    assert not report.passed
    assert report.missing == ("twelve_domain_validation",)


def test_single_gpu_requires_observed_identity_and_physical_execution():
    report = FabricVerificationMatrix().evaluate(
        ExecutionMode.SINGLE_GPU,
        {"physical_gpu_execution": True, "execution_identity": True},
    )
    assert report.passed


def test_block_four_modes_do_not_require_ncccl_evidence():
    for mode, evidence in (
        (ExecutionMode.TENSOR_PARALLEL, {"tensor_shard_plan": True}),
        (ExecutionMode.CONTEXT_PARALLEL, {"context_partition_plan": True}),
        (ExecutionMode.EXPERT_PARALLEL, {"expert_placement_plan": True}),
        (ExecutionMode.SHARDED_STATE, {"state_shard_plan": True, "checkpoint_compatible": True}),
    ):
        evidence.update({"physical_gpu_execution": True, "execution_identity": True})
        report = FabricVerificationMatrix().evaluate(mode, evidence)
        assert report.passed, (mode, report.missing)


def test_nccl_requires_collective_result_and_physical_node_proof():
    report = FabricVerificationMatrix().evaluate(
        ExecutionMode.NCCL,
        {"physical_gpu_execution": True, "execution_identity": True,
         "nccl_physical_proof": True, "distinct_physical_nodes": True,
         "collective_result_verified": False},
    )
    assert not report.passed
    assert report.missing == ("collective_result_verified",)


def test_readiness_reports_maturity_state():
    report = FabricVerificationMatrix().evaluate_fabric_readiness({
        "free_external_gpu_acquisition": True,
        "physical_gpu_execution": True,
        "multi_node_nccl": True,
        "twelve_domain_validation": True,
    })
    assert report.passed
    assert report.maturity_state == "physical_external_verified"
