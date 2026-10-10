"""Regression contract for the real two-node physical NCCL proof workflow.

These assertions protect the production evidence boundary. They intentionally
fail if the workflow stops checking physical prerequisites, loses stable rank
artifact paths, or relaxes the aggregate's two-host/two-GPU collective checks.
"""
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "physical-multi-node-nccl-proof.yml"


def test_physical_nccl_workflow_requires_real_cuda_and_nccl_runners():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'default: "main"' in workflow
    assert "nvidia-smi -L" in workflow
    assert "torch.cuda.is_available()" in workflow
    assert "torch.distributed.is_nccl_available()" in workflow
    assert 'WORLD_SIZE: "2"' in workflow
    assert 'THORIO_EXPECTED_NNODES: "2"' in workflow
    assert "lead_engine/nccl_all_reduce_probe.py" in workflow


def test_rank_evidence_uses_stable_artifact_directory_layout():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Stage rank evidence artifact with stable relative paths" in workflow
    assert "thorio-physical-nccl-rank-${RANK}" in workflow
    assert "physical-nccl-rank-${{ matrix.rank }}" in workflow
    assert "THORIO_NCCL_DOWNLOADED_ARTIFACT_FILES" in workflow
    assert 'expected_artifacts = {"physical-nccl-rank-0", "physical-nccl-rank-1"}' in workflow


def test_aggregate_keeps_strict_physical_collective_gates():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required_contract_fragments = (
        "rank-evidence.json",
        "proof_sha",
        "verified",
        "world_size",
        "nnodes",
        '"all_reduce"',
        "expected_sum",
        "distinct physical host",
        "distinct physical GPU UUIDs",
        "peer-connection evidence",
        "PHYSICAL MULTI-NODE NCCL VERIFIED",
    )
    for fragment in required_contract_fragments:
        assert fragment in workflow, f"physical NCCL proof gate missing: {fragment}"


def test_peer_transport_accepts_nccl_socket_channel_suffix_without_promoting_rdma():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'str(edge.get("transport") or "").strip().upper() == aggregate_transport' in workflow
    assert 'aggregate_transport + "/"' in workflow
    assert "hca_selections" in workflow
