"""Evidence-driven verification matrix for execution-fabric readiness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

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
    maturity_state: str = "discovered"

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            check.name for check in self.checks
            if check.required and not check.observed
        )


class FabricVerificationMatrix:
    """Evaluate evidence without converting plans into execution claims."""

    _COMMON = (
        "physical_gpu_execution",
        "execution_identity",
    )

    def evaluate(self, mode: ExecutionMode, evidence: Mapping[str, object]) -> FabricVerificationReport:
        names = list(self._COMMON)
        if mode in {ExecutionMode.SINGLE_GPU, ExecutionMode.BATCH_PARALLEL, ExecutionMode.DATA_PARALLEL}:
            pass
        elif mode in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            names.append("model_partition_plan")
        elif mode is ExecutionMode.TENSOR_PARALLEL:
            names.append("tensor_shard_plan")
        elif mode is ExecutionMode.CONTEXT_PARALLEL:
            names.append("context_partition_plan")
        elif mode is ExecutionMode.EXPERT_PARALLEL:
            names.append("expert_placement_plan")
        elif mode is ExecutionMode.SHARDED_STATE:
            names.extend(("state_shard_plan", "checkpoint_compatible"))
        elif mode is ExecutionMode.NCCL:
            names.extend((
                "nccl_physical_proof",
                "distinct_physical_nodes",
                "collective_result_verified",
            ))
        elif mode is ExecutionMode.HYBRID:
            names.extend(("hybrid_plan", "required_stage_evidence"))
        else:
            raise ValueError(f"unsupported verification mode: {mode}")

        checks = tuple(
            VerificationCheck(name, True, evidence.get(name) is True)
            for name in names
        )
        return FabricVerificationReport(
            mode,
            checks,
            all(check.observed for check in checks),
            self._mode_maturity(checks),
        )

    @staticmethod
    def _mode_maturity(checks: tuple[VerificationCheck, ...]) -> str:
        observed = sum(check.observed for check in checks)
        if observed == 0:
            return "discovered"
        if observed < len(checks):
            return "adapter_implemented"
        return "local_verified"

    def evaluate_fabric_readiness(self, evidence: Mapping[str, object]) -> FabricVerificationReport:
        checks = tuple(
            VerificationCheck(name, True, evidence.get(name) is True)
            for name in (
                "free_external_gpu_acquisition",
                "physical_gpu_execution",
                "multi_node_nccl",
                "twelve_domain_validation",
            )
        )
        passed = all(check.observed for check in checks)
        maturity = "physical_external_verified" if passed else self._readiness_maturity(checks)
        return FabricVerificationReport(ExecutionMode.HYBRID, checks, passed, maturity)

    @staticmethod
    def _readiness_maturity(checks: tuple[VerificationCheck, ...]) -> str:
        observed = sum(check.observed for check in checks)
        if observed == 0:
            return "discovered"
        if observed == 1:
            return "adapter_implemented"
        if observed == 2:
            return "local_verified"
        return "multi_gpu_verified"
