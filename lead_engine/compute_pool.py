"""Free compute inventory and capacity planning for the lead engine.

This module is intentionally provider-neutral. It never creates paid resources,
requests credentials, or assumes that logical agents are physical machines.
It measures the current host and produces a conservative worker budget that
can be consumed by supervisors or external schedulers.
"""
from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class ComputeCapacity:
    node_id: str
    cpu_count: int
    memory_mb: int
    architecture: str
    persistent: bool = False

    @property
    def recommended_workers(self) -> int:
        """Return a conservative CPU/memory-aware worker budget."""
        if self.cpu_count <= 0 or self.memory_mb <= 0:
            return 1
        cpu_budget = max(1, self.cpu_count - 1)
        memory_budget = max(1, self.memory_mb // 2048)
        return max(1, min(cpu_budget, memory_budget))

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["recommended_workers"] = self.recommended_workers
        return result


def _memory_mb() -> int:
    """Read Linux memory without requiring a third-party dependency."""
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if match:
            return max(1, int(match.group(1)) // 1024)
    return max(1, int(os.environ.get("THORIO_COMPUTE_MEMORY_MB", "2048")))


def local_capacity(*, node_id: str | None = None, persistent: bool = False) -> ComputeCapacity:
    """Describe the machine currently executing the engine."""
    cpu_count = os.cpu_count() or 1
    resolved_id = (node_id or os.environ.get("THORIO_NODE_ID") or platform.node() or "local").strip()
    if not resolved_id:
        resolved_id = "local"
    return ComputeCapacity(
        node_id=resolved_id,
        cpu_count=cpu_count,
        memory_mb=_memory_mb(),
        architecture=platform.machine() or "unknown",
        persistent=persistent,
    )


def worker_budget(capacity: ComputeCapacity, *, requested: int | None = None) -> int:
    """Bound requested concurrency by actual free capacity and safe limits."""
    if not isinstance(capacity, ComputeCapacity):
        raise ValueError("capacity must be a ComputeCapacity instance")
    if requested is not None and (isinstance(requested, bool) or requested <= 0):
        raise ValueError("requested worker count must be positive")
    configured = int(os.environ.get("THORIO_MAX_LOCAL_WORKERS", "0"))
    if configured < 0:
        raise ValueError("THORIO_MAX_LOCAL_WORKERS must not be negative")
    limit = capacity.recommended_workers
    if configured:
        limit = min(limit, configured)
    if requested is not None:
        limit = min(limit, requested)
    return max(1, limit)


def pool_snapshot(capacities: Mapping[str, ComputeCapacity]) -> Dict[str, Any]:
    """Return an auditable snapshot of all known free compute nodes."""
    if not isinstance(capacities, Mapping):
        raise ValueError("capacities must be a mapping")
    if any(not isinstance(value, ComputeCapacity) for value in capacities.values()):
        raise ValueError("all pool entries must be ComputeCapacity instances")
    nodes = {str(key): value.to_dict() for key, value in capacities.items()}
    return {
        "free_only": True,
        "node_count": len(nodes),
        "total_cpu": sum(item["cpu_count"] for item in nodes.values()),
        "total_memory_mb": sum(item["memory_mb"] for item in nodes.values()),
        "total_recommended_workers": sum(item["recommended_workers"] for item in nodes.values()),
        "nodes": nodes,
    }
