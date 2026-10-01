"""Provider-neutral execution contract and deterministic planner skeleton.

This module defines the common control-plane vocabulary shared by every future
execution adapter. It does not start work, reserve resources, claim physical
execution, or implement a parallel runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence


class ExecutionMode(str, Enum):
    SINGLE_GPU = "single_gpu"
    BATCH_PARALLEL = "batch_parallel"
    DATA_PARALLEL = "data_parallel"
    PIPELINE_PARALLEL = "pipeline_parallel"
    TENSOR_PARALLEL = "tensor_parallel"
    CONTEXT_PARALLEL = "context_parallel"
    EXPERT_PARALLEL = "expert_parallel"
    SHARDED_STATE = "sharded_state"
    P2P_MODEL_PARTITION = "p2p_model_partition"
    NCCL = "nccl"
    HYBRID = "hybrid"


_MULTI_RESOURCE_MODES = frozenset(
    {
        ExecutionMode.DATA_PARALLEL,
        ExecutionMode.PIPELINE_PARALLEL,
        ExecutionMode.TENSOR_PARALLEL,
        ExecutionMode.CONTEXT_PARALLEL,
        ExecutionMode.EXPERT_PARALLEL,
        ExecutionMode.SHARDED_STATE,
        ExecutionMode.P2P_MODEL_PARTITION,
        ExecutionMode.NCCL,
        ExecutionMode.HYBRID,
    }
)


@dataclass(frozen=True)
class ExecutionWorkload:
    workload_id: str
    allowed_modes: tuple[ExecutionMode, ...]
    min_workers: int = 1
    max_workers: int | None = None
    checkpoint_required: bool = False
    elastic: bool = False
    requires_physical_gpu: bool = True
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        workload_id = self.workload_id.strip()
        if not workload_id:
            raise ValueError("workload_id is required")
        object.__setattr__(self, "workload_id", workload_id)

        modes = tuple(self.allowed_modes)
        if not modes:
            raise ValueError("allowed_modes must not be empty")
        if any(not isinstance(mode, ExecutionMode) for mode in modes):
            raise ValueError("allowed_modes must contain ExecutionMode values")
        if len(set(modes)) != len(modes):
            raise ValueError("allowed_modes must be unique")
        object.__setattr__(self, "allowed_modes", modes)

        if self.min_workers < 1:
            raise ValueError("min_workers must be positive")
        if self.max_workers is not None and self.max_workers < self.min_workers:
            raise ValueError("max_workers must be >= min_workers")

        normalized = []
        for key, value in self.metadata:
            key = str(key).strip()
            if not key or value is None:
                raise ValueError("metadata keys and values must be non-empty")
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    raise ValueError("metadata string values must be non-empty")
            elif not isinstance(value, (int, float, bool)):
                raise ValueError("metadata values must be scalar")
            normalized.append((key, value))
        if len({key for key, _ in normalized}) != len(normalized):
            raise ValueError("metadata keys must be unique")
        object.__setattr__(self, "metadata", tuple(normalized))


@dataclass(frozen=True)
class ExecutionCapability:
    resource_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    provider_id: str
    domain_id: str
    supported_modes: tuple[ExecutionMode, ...]
    physical_gpu_verified: bool
    backends: tuple[str, ...] = field(default_factory=tuple)
    interconnects: tuple[str, ...] = field(default_factory=tuple)
    network_bandwidth_gbps: float | None = None
    network_latency_us: float | None = None
    checkpointing_supported: bool = False
    elastic_membership_supported: bool = False
    trusted: bool = False

    def __post_init__(self) -> None:
        resource_ids = tuple(str(item).strip() for item in self.resource_ids)
        node_ids = tuple(str(item).strip() for item in self.node_ids)
        if not resource_ids or any(not item for item in resource_ids):
            raise ValueError("resource_ids must contain at least one resource")
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("resource_ids must be unique")
        if not node_ids or any(not item for item in node_ids):
            raise ValueError("node_ids must contain at least one node")
        if len(node_ids) != len(resource_ids):
            raise ValueError("node_ids must align one-to-one with resource_ids")
        if not self.provider_id.strip() or not self.domain_id.strip():
            raise ValueError("provider_id and domain_id are required")

        modes = tuple(self.supported_modes)
        if any(not isinstance(mode, ExecutionMode) for mode in modes):
            raise ValueError("supported_modes must contain ExecutionMode values")
        if len(set(modes)) != len(modes):
            raise ValueError("supported_modes must be unique")

        if self.network_bandwidth_gbps is not None and self.network_bandwidth_gbps <= 0:
            raise ValueError("network_bandwidth_gbps must be positive")
        if self.network_latency_us is not None and self.network_latency_us <= 0:
            raise ValueError("network_latency_us must be positive")

        object.__setattr__(self, "resource_ids", resource_ids)
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "supported_modes", modes)
        object.__setattr__(self, "backends", tuple(str(item).strip() for item in self.backends if str(item).strip()))
        object.__setattr__(self, "interconnects", tuple(str(item).strip() for item in self.interconnects if str(item).strip()))

    @property
    def worker_count(self) -> int:
        return len(self.resource_ids)

    @property
    def resource_count(self) -> int:
        return len(self.resource_ids)


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    workload_id: str
    mode: ExecutionMode
    provider_id: str
    domain_id: str
    resource_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    worker_count: int
    evidence_state: str = "plan_only"
    execution_started: bool = False
    physical_execution_verified: bool = False

    def __post_init__(self) -> None:
        if not self.plan_id.strip() or not self.workload_id.strip():
            raise ValueError("plan_id and workload_id are required")
        if not isinstance(self.mode, ExecutionMode):
            raise ValueError("mode must be an ExecutionMode")
        if not self.resource_ids or len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("plan resource_ids must be unique and non-empty")
        if not self.node_ids or any(not str(item).strip() for item in self.node_ids):
            raise ValueError("plan node_ids must be non-empty")
        if len(self.node_ids) != len(self.resource_ids):
            raise ValueError("plan node_ids must align one-to-one with resource_ids")
        if self.worker_count != len(self.resource_ids):
            raise ValueError("worker_count must match resource_ids")
        if self.execution_started or self.physical_execution_verified:
            raise ValueError("planner cannot claim execution evidence")


class ExecutionPlanner:
    """Deterministic plan-only seam for future execution adapters."""

    def plan(
        self,
        workload: ExecutionWorkload,
        capabilities: Sequence[ExecutionCapability],
    ) -> ExecutionPlan:
        if not isinstance(workload, ExecutionWorkload):
            raise TypeError("workload must be ExecutionWorkload")
        candidates = tuple(capabilities)
        if not candidates:
            raise ValueError("no execution capabilities supplied")

        seen_resources: set[str] = set()
        for capability in candidates:
            duplicates = seen_resources.intersection(capability.resource_ids)
            if duplicates:
                raise ValueError(f"duplicate resources across capabilities: {sorted(duplicates)}")
            seen_resources.update(capability.resource_ids)

        eligible = tuple(
            capability
            for capability in candidates
            if (not workload.requires_physical_gpu or capability.physical_gpu_verified)
        )
        if not eligible:
            raise ValueError("no capability has physical GPU verification")

        for mode in workload.allowed_modes:
            supported = tuple(
                capability
                for capability in eligible
                if mode in capability.supported_modes
            )
            if not supported:
                continue

            selected = self._select(mode, supported, workload)
            if selected is None:
                continue

            resource_ids = tuple(
                resource_id
                for capability in selected
                for resource_id in capability.resource_ids
            )
            node_ids = tuple(
                node_id
                for capability in selected
                for node_id in capability.node_ids
            )
            if mode is ExecutionMode.SINGLE_GPU:
                resource_ids = resource_ids[:1]
                node_ids = node_ids[:1]

            provider_ids = {capability.provider_id for capability in selected}
            domain_ids = {capability.domain_id for capability in selected}
            if len(provider_ids) != 1 or len(domain_ids) != 1:
                raise ValueError("plan currently requires one provider and domain")

            if mode in _MULTI_RESOURCE_MODES and len(resource_ids) < 2:
                continue

            plan_id = self._plan_id(
                workload,
                mode,
                resource_ids,
                node_ids,
                selected[0].provider_id,
                selected[0].domain_id,
            )
            return ExecutionPlan(
                plan_id=plan_id,
                workload_id=workload.workload_id,
                mode=mode,
                provider_id=selected[0].provider_id,
                domain_id=selected[0].domain_id,
                resource_ids=resource_ids,
                node_ids=node_ids,
                worker_count=len(node_ids),
            )

        raise ValueError("no supported execution mode satisfies the supplied capabilities")

    @staticmethod
    def _select(
        mode: ExecutionMode,
        capabilities: Sequence[ExecutionCapability],
        workload: ExecutionWorkload,
    ) -> tuple[ExecutionCapability, ...] | None:
        ordered = tuple(sorted(capabilities, key=lambda item: (item.provider_id, item.domain_id, item.node_ids, item.resource_ids)))
        if mode is ExecutionMode.SINGLE_GPU:
            return ordered[:1]

        selected: list[ExecutionCapability] = []
        resource_count = 0
        for capability in ordered:
            if workload.max_workers is not None and len(selected) >= workload.max_workers:
                break
            selected.append(capability)
            resource_count += capability.resource_count
            if len(selected) >= workload.min_workers and resource_count >= 2:
                break

        if resource_count < workload.min_workers:
            return None
        return tuple(selected)

    @staticmethod
    def _plan_id(
        workload: ExecutionWorkload,
        mode: ExecutionMode,
        resource_ids: Sequence[str],
        node_ids: Sequence[str],
        provider_id: str,
        domain_id: str,
    ) -> str:
        material = {
            "workload_id": workload.workload_id,
            "mode": mode.value,
            "resource_ids": list(resource_ids),
            "node_ids": list(node_ids),
            "provider_id": provider_id,
            "domain_id": domain_id,
            "metadata": list(workload.metadata),
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
