# Physical multi-node NCCL proof record

## Verified run

- GitHub Actions run: [38022153428](https://github.com/DocSentinelX12/Thorio-Lead-Engine/actions/runs/38022153428)
- Proof ref: `main`
- Exact source revision checked out by both ranks and the aggregate: `1741c3a5c2b3355c6aaf72f02f71d192292b570a`
- Aggregate result: `PHYSICAL MULTI-NODE NCCL VERIFIED`
- Outcome: passed on both rank jobs, the evidence aggregation job, and worker/runner cleanup.

## What the run proved

- Two separately provisioned free Kaggle GPU workers came online as JIT GitHub Actions runners.
- Both physical workers passed the local NVIDIA/CUDA/NCCL prerequisites.
- The ranks reported Tesla T4 GPUs, two distinct physical host identities, and two distinct GPU UUIDs.
- Both ranks ran a two-node NCCL `all_reduce` and verified the expected result of `3`.
- Both rank evidence records were bound to the exact proof revision, downloaded from the expected per-rank artifact directories, and accepted by the strict aggregate validator.
- NCCL debug logs contained cross-rank peer-connection evidence. The selected transport was **Socket**; the observed channel transport was `Socket/0`.
- The cleanup job completed successfully, releasing the run-owned Kaggle workers and removing the run-owned JIT runner registrations.

## Scope and limitations

This is a real external, physical two-node NCCL collective proof, not a simulated result. It proves that the demonstrated two-node Socket path can execute the tested collective.

It does **not** prove InfiniBand/RDMA, a performance target, continuous availability of Kaggle capacity, every model-parallel mode, or the full twelve-domain production readiness gate. Socket success must not be relabeled as RDMA success. A successful historical run also does not mean its ephemeral GPUs remain available after cleanup.

The run's downloadable rank artifacts remain the detailed per-rank evidence. This record is a durable index to the run and its validated scope, not a substitute for re-running the proof when the runtime, provider bootstrap, relay, or proof contract changes.

## Regression protection

`tests/test_physical_nccl_proof_workflow_contract.py` guards the workflow's physical CUDA/NCCL prerequisites, stable rank-artifact layout, and strict aggregate evidence requirements. These checks supplement the live external proof; they do not replace it.
