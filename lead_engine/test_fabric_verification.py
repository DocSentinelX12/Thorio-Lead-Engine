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
