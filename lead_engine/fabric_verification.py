"""Evidence-driven verification matrix for the execution fabric."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .execution_fabric_contract import ExecutionMode


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    required: bool
    observed: bool


@dataclass(frozen=True)
class FabricVerificationReport:
    mode: ExecutionMode
    checks: tuple[VerificationCheck, ...]
    passed: bool

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if check.required and not check.observed)


class FabricVerificationMatrix:
    def evaluate(
        self,
        mode: ExecutionMode,
        evidence: Mapping[str, object],
    ) -> FabricVerificationReport:
        common = [
            VerificationCheck("physical_gpu_execution", True, evidence.get("physical_gpu_execution") is True),
            VerificationCheck("execution_identity", True, evidence.get("execution_identity") is True),
        ]
        if mode in {ExecutionMode.SINGLE_GPU, ExecutionMode.BATCH_PARALLEL, ExecutionMode.DATA_PARALLEL}:
            checks = common
        elif mode in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            checks = common + [
                VerificationCheck("model_partition_plan", True, evidence.get("model_partition_plan") is True),
            ]
        elif mode in {
            ExecutionMode.TENSOR_PARALLEL, ExecutionMode.CONTEXT_PARALLEL,
            ExecutionMode.EXPERT_PARALLEL, ExecutionMode.SHARDED_STATE,
            ExecutionMode.NCCL,
        }:
            checks = common + [
                VerificationCheck("nccl_physical_proof", True, evidence.get("nccl_physical_proof") is True),
                VerificationCheck("distinct_physical_nodes", True, evidence.get("distinct_physical_nodes") is True),
            ]
        elif mode is ExecutionMode.HYBRID:
            checks = common + [
                VerificationCheck("model_partition_plan", True, evidence.get("model_partition_plan") is True),
                VerificationCheck("nccl_physical_proof", True, evidence.get("nccl_physical_proof") is True),
                VerificationCheck("distinct_physical_nodes", True, evidence.get("distinct_physical_nodes") is True),
            ]
        else:
            raise ValueError(f"unsupported verification mode: {mode}")

        return FabricVerificationReport(mode, tuple(checks), all(
            not check.required or check.observed for check in checks
        ))

    def evaluate_fabric_readiness(self, evidence: Mapping[str, object]) -> FabricVerificationReport:
        required = (
            VerificationCheck("free_external_gpu_acquisition", True, evidence.get("free_external_gpu_acquisition") is True),
            VerificationCheck("physical_gpu_execution", True, evidence.get("physical_gpu_execution") is True),
            VerificationCheck("multi_node_nccl", True, evidence.get("multi_node_nccl") is True),
            VerificationCheck("twelve_domain_validation", True, evidence.get("twelve_domain_validation") is True),
        )
        return FabricVerificationReport(ExecutionMode.HYBRID, required, all(check.observed for check in required))
