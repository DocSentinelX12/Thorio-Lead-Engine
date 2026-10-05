"""Production integration seam for the execution-fabric architecture.

This module composes the universal execution contract with the mode-specific
planning layers. It is deliberately provider-neutral: physical acquisition
and resource reservation remain owned by ComputeCoordinator/ComputeScheduler.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .advanced_parallel_execution import (
    AdvancedParallelPlanner,
    ContextPartitionSpec,
    ExpertSpec,
    ShardedStateSpec,
    TensorShardSpec,
)
from .execution_fabric_contract import (
    ExecutionCapability,
    ExecutionMode,
    ExecutionPlan,
    ExecutionPlanner,
    ExecutionWorkload,
)
from .hybrid_execution_planner import HybridExecutionPlanner
from .model_partitioning import ModelLayer, ModelPartitionPlanner
from .model_partition_execution import ModelPartitionExecutionPlanner
from .nccl_execution import NCCLExecutionPlanner, NCCLLaunchSpec


@dataclass(frozen=True)
class IntegratedExecutionPlan:
    execution_plan: ExecutionPlan
    mode_details: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.execution_plan.plan_id,
            "workload_id": self.execution_plan.workload_id,
            "mode": self.execution_plan.mode.value,
            "provider_id": self.execution_plan.provider_id,
            "domain_id": self.execution_plan.domain_id,
            "resource_ids": list(self.execution_plan.resource_ids),
            "node_ids": list(self.execution_plan.node_ids),
            "worker_count": self.execution_plan.worker_count,
            "evidence_state": self.execution_plan.evidence_state,
            "execution_started": self.execution_plan.execution_started,
            "physical_execution_verified": self.execution_plan.physical_execution_verified,
            "mode_details": ProductionExecutionFabric._jsonable(self.mode_details),
        }


class ProductionExecutionFabric:
    """Compose all execution layers without claiming physical execution."""

    def __init__(
        self,
        *,
        planner: ExecutionPlanner | None = None,
        model_partitions: ModelPartitionPlanner | None = None,
        partition_execution: ModelPartitionExecutionPlanner | None = None,
        advanced: AdvancedParallelPlanner | None = None,
        nccl: NCCLExecutionPlanner | None = None,
        hybrid: HybridExecutionPlanner | None = None,
    ) -> None:
        self.planner = planner or ExecutionPlanner()
        self.model_partitions = model_partitions or ModelPartitionPlanner()
        self.partition_execution = partition_execution or ModelPartitionExecutionPlanner()
        self.advanced = advanced or AdvancedParallelPlanner()
        self.nccl = nccl or NCCLExecutionPlanner()
        self.hybrid = hybrid or HybridExecutionPlanner()

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(k): ProductionExecutionFabric._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [ProductionExecutionFabric._jsonable(v) for v in value]
        if isinstance(value, ExecutionMode):
            return value.value
        if hasattr(value, "__dataclass_fields__"):
            return ProductionExecutionFabric._jsonable(asdict(value))
        return value

    @staticmethod
    def _mode(payload: Mapping[str, Any]) -> ExecutionMode:
        raw = str(payload.get("execution_mode") or payload.get("execution_strategy") or "").strip()
        if not raw and str(payload.get("kind") or "").strip() == "gpu_workload":
            raw = ExecutionMode.SINGLE_GPU.value
        if not raw:
            gpu_requirements = payload.get("compute_requirements", {}).get("gpu", {})
            if isinstance(gpu_requirements, Mapping):
                gpu_count = int(gpu_requirements.get("gpu_count", 0) or 0)
                if bool(gpu_requirements.get("require_nccl")) or gpu_count > 1:
                    raw = ExecutionMode.NCCL.value
                else:
                    raw = ExecutionMode.SINGLE_GPU.value
            else:
                raw = ExecutionMode.SINGLE_GPU.value
        try:
            return ExecutionMode(raw)
        except ValueError as exc:
            raise ValueError(f"unsupported execution_mode: {raw or '<missing>'}") from exc

    @staticmethod
    def _allocation_capability(
        payload: Mapping[str, Any],
        allocation: Mapping[str, Any],
        mode: ExecutionMode,
        supported_modes: Sequence[ExecutionMode] | None = None,
    ) -> ExecutionCapability:
        resource_ids = tuple(str(x).strip() for x in allocation.get("resource_ids") or ())
        node_ids = tuple(str(x).strip() for x in allocation.get("node_ids") or ())
        if not resource_ids or not node_ids:
            raise ValueError("physical allocation must contain resource_ids and node_ids")
        evidence = tuple(x for x in allocation.get("capability_evidence") or () if isinstance(x, Mapping))
        if not evidence:
            raise ValueError("physical allocation must contain capability evidence")
        gpu_evidence = tuple(
            item for item in evidence
            if "/gpu/" in str(item.get("resource_id") or "") or "/gpu-" in str(item.get("resource_id") or "")
        )
        if not gpu_evidence:
            raise ValueError("physical allocation contains no GPU capability evidence")
        physical_gpu_verified = all(
            str(item.get("gpu_uuid") or "").strip() and str(item.get("resource_id") or "").strip()
            for item in gpu_evidence
        )
        raw_backends = payload.get("backends") or payload.get("compute_requirements", {}).get("gpu", {}).get("backends") or ()
        backends = tuple(str(x).strip().lower() for x in raw_backends if str(x).strip())
        if mode is ExecutionMode.NCCL and "nccl" not in backends:
            backends = (*backends, "nccl")
        return ExecutionCapability(
            resource_ids=resource_ids,
            node_ids=node_ids,
            provider_id=str(allocation.get("provider_id") or "").strip(),
            domain_id=str(allocation.get("domain_id") or "").strip(),
            supported_modes=tuple(supported_modes or (mode,)),
            physical_gpu_verified=physical_gpu_verified,
            backends=backends,
            interconnects=tuple(str(x).strip() for x in payload.get("interconnects") or () if str(x).strip()),
            network_bandwidth_gbps=payload.get("network_bandwidth_gbps"),
            network_latency_us=payload.get("network_latency_us"),
            checkpointing_supported=bool(payload.get("checkpoint_required") or payload.get("checkpoint_path")),
            elastic_membership_supported=bool(payload.get("elastic")),
            trusted=bool(payload.get("trusted")),
        )

    def plan(
        self,
        payload: Mapping[str, Any],
        allocation: Mapping[str, Any],
        *,
        rendezvous_endpoint: str | None = None,
        workload_id: str | None = None,
    ) -> IntegratedExecutionPlan:
        if not isinstance(payload, Mapping) or not isinstance(allocation, Mapping):
            raise TypeError("payload and allocation must be mappings")
        mode = self._mode(payload)
        workload_id = str(workload_id or payload.get("workload_id") or payload.get("task_id") or "").strip()
        if not workload_id:
            raise ValueError("workload_id is required for execution planning")
        resource_count = len(tuple(allocation.get("resource_ids") or ()))
        hybrid_stages = tuple(ExecutionMode(str(item)) for item in payload.get("hybrid_stages") or ()) if mode is ExecutionMode.HYBRID else ()
        supported_modes = (ExecutionMode.HYBRID, *hybrid_stages) if mode is ExecutionMode.HYBRID else (mode,)
        min_workers = 1 if mode in {
            ExecutionMode.SINGLE_GPU,
            ExecutionMode.BATCH_PARALLEL,
            ExecutionMode.DATA_PARALLEL,
        } and resource_count == 1 else 2
        workload = ExecutionWorkload(
            workload_id=workload_id,
            allowed_modes=(mode,),
            min_workers=min_workers,
            max_workers=resource_count or None,
            checkpoint_required=bool(payload.get("checkpoint_required") or payload.get("checkpoint_path")),
            elastic=bool(payload.get("elastic")),
            requires_physical_gpu=True,
        )
        capability = self._allocation_capability(payload, allocation, mode, supported_modes)
        base = self.planner.plan(workload, (capability,))
        details: dict[str, Any] = {"integration_version": 1}

        if mode in {ExecutionMode.PIPELINE_PARALLEL, ExecutionMode.P2P_MODEL_PARTITION}:
            raw_layers = payload.get("model_layers")
            if raw_layers is not None:
                if not isinstance(raw_layers, Sequence) or isinstance(raw_layers, (str, bytes)):
                    raise ValueError("model_layers must be a sequence")
                layers = tuple(
                    ModelLayer(
                        layer_id=str(item["layer_id"]),
                        ordinal=int(item["ordinal"]),
                        parameter_bytes=int(item["parameter_bytes"]),
                    )
                    for item in raw_layers
                    if isinstance(item, Mapping)
                )
                partition_plan = self.model_partitions.plan(base, layers)
                details["model_partition_plan"] = asdict(partition_plan)
                transport = str(payload.get("partition_transport") or "p2p")
                details["partition_execution_spec"] = asdict(
                    self.partition_execution.build(base, partition_plan, transport=transport)
                )

        elif mode in {
            ExecutionMode.TENSOR_PARALLEL,
            ExecutionMode.CONTEXT_PARALLEL,
            ExecutionMode.EXPERT_PARALLEL,
            ExecutionMode.SHARDED_STATE,
        }:
            advanced_payload: dict[str, Any] = {}
            if mode is ExecutionMode.TENSOR_PARALLEL and payload.get("tensor_shards") is not None:
                specs = tuple(
                    TensorShardSpec(
                        tensor_id=str(item["tensor_id"]),
                        strategy=str(item["strategy"]),
                        shard_count=int(item["shard_count"]),
                    )
                    for item in payload["tensor_shards"]
                )
                advanced_payload["tensor_shard_plan"] = asdict(self.advanced.tensor_plan(base, specs))
            elif mode is ExecutionMode.CONTEXT_PARALLEL and payload.get("context_partition") is not None:
                item = payload["context_partition"]
                spec = ContextPartitionSpec(
                    sequence_length=int(item["sequence_length"]),
                    partition_count=int(item.get("partition_count", base.worker_count)),
                    dimension=str(item.get("dimension", "sequence")),
                )
                advanced_payload["context_partition_plan"] = asdict(self.advanced.context_plan(base, spec))
            elif mode is ExecutionMode.EXPERT_PARALLEL and payload.get("experts") is not None:
                specs = tuple(
                    ExpertSpec(expert_id=str(item["expert_id"]), rank=int(item["rank"]))
                    for item in payload["experts"]
                )
                advanced_payload["expert_parallel_plan"] = asdict(self.advanced.expert_plan(base, specs))
            elif mode is ExecutionMode.SHARDED_STATE and payload.get("sharded_state") is not None:
                item = payload["sharded_state"]
                spec = ShardedStateSpec(
                    parameter_bytes=int(item["parameter_bytes"]),
                    gradient_bytes=int(item["gradient_bytes"]),
                    optimizer_bytes=int(item["optimizer_bytes"]),
                    shard_count=int(item.get("shard_count", base.worker_count)),
                    reshard_after_forward=bool(item.get("reshard_after_forward", True)),
                    reshard_after_backward=bool(item.get("reshard_after_backward", True)),
                    checkpoint_required=bool(item.get("checkpoint_required", True)),
                )
                advanced_payload["sharded_state_plan"] = asdict(self.advanced.sharded_state_plan(base, spec))
            details.update(advanced_payload)

        elif mode is ExecutionMode.NCCL:
            launch = payload.get("nccl_launch") or {}
            master_addr = str(launch.get("master_addr") or "").strip()
            master_port = int(launch.get("master_port", 29500))
            if rendezvous_endpoint:
                master_addr, port_text = str(rendezvous_endpoint).rsplit(":", 1)
                master_port = int(port_text)
            if not master_addr:
                master_addr = "127.0.0.1"
            spec = NCCLLaunchSpec(
                master_addr=master_addr,
                master_port=master_port,
                socket_interface=str(launch.get("socket_interface") or "auto"),
                collective=str(launch.get("collective") or "all_reduce"),
            )
            details["nccl_execution_plan"] = asdict(self.nccl.plan(base, spec))

        elif mode is ExecutionMode.HYBRID:
            stages = hybrid_stages
            if not stages:
                raise ValueError("hybrid_stages is required for hybrid execution")
            details["hybrid_execution_plan"] = asdict(self.hybrid.plan(base, stages, (capability,)))

        return IntegratedExecutionPlan(base, details)
