"""Provider-neutral physical compute resource model for the Thorio compute fabric.

This module deliberately contains no scheduling policy, database access, GPU driver calls,
or business-state mutation. It defines the durable vocabulary that later layers can consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class ResourceState(str, Enum):
    DISCOVERED = "discovered"
    PROBING = "probing"
    HEALTHY = "healthy"
    AVAILABLE = "available"
    RESERVED = "reserved"
    LEASED = "leased"
    EXECUTING = "executing"
    RELEASED = "released"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"


class WorkloadClass(str, Enum):
    IO_BOUND = "io_bound"
    CPU_BOUND = "cpu_bound"
    GPU_OPTIONAL = "gpu_optional"
    GPU_REQUIRED = "gpu_required"
    MULTI_GPU = "multi_gpu"
    MULTI_NODE_GPU = "multi_node_gpu"
    HYBRID_CPU_GPU = "hybrid_cpu_gpu"


@dataclass(frozen=True)
class GpuResource:
    node_id: str
    gpu_id: str
    gpu_uuid: Optional[str] = None
    model: Optional[str] = None
    vram_bytes: Optional[int] = None
    compute_capability: Optional[str] = None
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    pci_bus_id: Optional[str] = None
    numa_node: Optional[int] = None
    nvlink_domain: Optional[str] = None
    topology_domain: Optional[str] = None
    topology_source: Optional[str] = None
    health_state: ResourceState = ResourceState.DISCOVERED
    availability_state: ResourceState = ResourceState.DISCOVERED

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.gpu_id.strip():
            raise ValueError("node_id and gpu_id are required")
        if self.vram_bytes is not None and self.vram_bytes < 0:
            raise ValueError("vram_bytes must not be negative")
        if self.numa_node is not None and self.numa_node < 0:
            raise ValueError("numa_node must not be negative")

    @property
    def resource_id(self) -> str:
        return f"{self.node_id}/{self.gpu_id}"

    @property
    def identity_key(self) -> str:
        return self.gpu_uuid.strip() if self.gpu_uuid and self.gpu_uuid.strip() else self.resource_id


@dataclass(frozen=True)
class CpuResource:
    node_id: str
    cpu_count: int
    memory_bytes: int

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id is required")
        if self.cpu_count < 1 or self.memory_bytes < 1:
            raise ValueError("CPU count and memory must be positive")


@dataclass(frozen=True)
class NodeResource:
    node_id: str
    architecture: str
    cpu: CpuResource
    gpus: Tuple[GpuResource, ...] = field(default_factory=tuple)
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    nccl_version: Optional[str] = None
    nic_names: Tuple[str, ...] = field(default_factory=tuple)
    state: ResourceState = ResourceState.DISCOVERED

    def __post_init__(self) -> None:
        if not self.node_id.strip() or self.cpu.node_id != self.node_id:
            raise ValueError("node_id must match CPU resource node_id")
        if any(gpu.node_id != self.node_id for gpu in self.gpus):
            raise ValueError("all GPUs must belong to the node")

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)


@dataclass(frozen=True)
class GpuRequirements:
    gpu_count: int = 0
    min_vram_bytes: Optional[int] = None
    min_compute_capability: Optional[str] = None
    required_cuda_version: Optional[str] = None
    required_driver_version: Optional[str] = None
    required_nvlink_domain: Optional[str] = None
    require_nccl: bool = False
    min_fabric_bandwidth_gbps: Optional[float] = None
    max_fabric_latency_us: Optional[float] = None
    require_redundant_fabric_path: bool = False

    def __post_init__(self) -> None:
        if self.gpu_count < 0:
            raise ValueError("gpu_count must not be negative")
        for name in ("min_vram_bytes",):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.require_nccl and self.gpu_count < 2:
            raise ValueError("NCCL requirement is meaningful only for multi-GPU work")
        if self.min_fabric_bandwidth_gbps is not None and self.min_fabric_bandwidth_gbps <= 0:
            raise ValueError("min_fabric_bandwidth_gbps must be positive")
        if self.max_fabric_latency_us is not None and self.max_fabric_latency_us <= 0:
            raise ValueError("max_fabric_latency_us must be positive")


@dataclass(frozen=True)
class ComputeRequirements:
    workload_class: WorkloadClass
    gpu: GpuRequirements = field(default_factory=GpuRequirements)
    min_cpu_count: int = 1
    min_memory_bytes: int = 1
    same_node: bool = True
    topology_domain: Optional[str] = None
    allowed_node_ids: Tuple[str, ...] = field(default_factory=tuple)
    performance_signature: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.min_cpu_count < 1 or self.min_memory_bytes < 1:
            raise ValueError("minimum CPU and memory requirements must be positive")
        if self.workload_class == WorkloadClass.MULTI_NODE_GPU and self.same_node:
            raise ValueError("multi-node GPU work cannot require same_node")
        if any(not str(node_id).strip() for node_id in self.allowed_node_ids):
            raise ValueError("allowed_node_ids must contain non-empty node IDs")
        if len(set(self.allowed_node_ids)) != len(self.allowed_node_ids):
            raise ValueError("allowed_node_ids must be unique")
        normalized_signature = tuple((str(key).strip(), str(value).strip()) for key, value in self.performance_signature)
        if any(not key or not value for key, value in normalized_signature):
            raise ValueError("performance_signature keys and values must be non-empty")
        if len({key for key, _ in normalized_signature}) != len(normalized_signature):
            raise ValueError("performance_signature keys must be unique")
        object.__setattr__(self, "performance_signature", normalized_signature)


@dataclass(frozen=True)
class ResourceLease:
    lease_id: str
    task_id: str
    generation: int
    resource_ids: Tuple[str, ...]
    expires_at: float

    def __post_init__(self) -> None:
        if not self.lease_id.strip() or not self.task_id.strip():
            raise ValueError("lease_id and task_id are required")
        if self.generation < 1:
            raise ValueError("generation must be positive")
        if not self.resource_ids:
            raise ValueError("a lease must contain at least one resource")
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("resource IDs in a lease must be unique")
        if self.expires_at <= 0:
            raise ValueError("expires_at must be positive")
