"""Evidence-only execution telemetry for the GPU fabric.

This module extracts measurements already observed by the distributed runtime.
It never invents performance values, health scores, or scheduling policy.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def physical_path_key(path: Mapping[str, Any]) -> str:
    """Return a stable identity for one observed physical GPU-to-NIC/RDMA path."""
    normalized = {
        str(key): path[key]
        for key in (
            "node_id", "gpu_uuid", "nic", "nic_pci_bus_id",
            "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer",
        )
        if path.get(key) is not None and str(path.get(key)).strip() != ""
    }
    if not normalized:
        return ""
    serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def extract_execution_metrics(verification: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one metric record per rank with an observed all-reduce duration."""
    process_evidence = verification.get("process_evidence")
    if not isinstance(process_evidence, list):
        return ()

    metrics: list[dict[str, Any]] = []
    for item in process_evidence:
        if not isinstance(item, Mapping):
            continue
        probe = item.get("probe")
        if not isinstance(probe, Mapping):
            continue
        elapsed = probe.get("all_reduce_elapsed_ms")
        try:
            elapsed_ms = float(elapsed)
        except (TypeError, ValueError):
            continue
        if elapsed_ms <= 0:
            continue
        gpu_binding = item.get("gpu_binding")
        physical_path = (
            gpu_binding.get("planned_physical_path")
            if isinstance(gpu_binding, Mapping)
            else None
        )
        path = physical_path if isinstance(physical_path, Mapping) else {}
        metrics.append({
            "rank": int(item.get("rank", probe.get("rank", -1))),
            "gpu_uuid": str(probe.get("gpu_uuid") or "").strip(),
            "node_id": str(gpu_binding.get("node_id") or "").strip()
                if isinstance(gpu_binding, Mapping) else "",
            "transport": str(probe.get("network_transport") or "").strip() or None,
            "all_reduce_elapsed_ms": elapsed_ms,
            "physical_path": dict(path),
            "path_key": physical_path_key(path),
        })
    return tuple(sorted(metrics, key=lambda item: (int(item["rank"]), str(item["gpu_uuid"]))))


def aggregate_execution_metrics(metrics: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Aggregate only observed rank measurements for one execution."""
    if not metrics:
        return {"sample_count": 0}
    values = [float(item["all_reduce_elapsed_ms"]) for item in metrics]
    transports = sorted({str(item["transport"]) for item in metrics if item.get("transport")})
    return {
        "sample_count": len(values),
        "min_all_reduce_elapsed_ms": min(values),
        "max_all_reduce_elapsed_ms": max(values),
        "avg_all_reduce_elapsed_ms": sum(values) / len(values),
        "transport": transports[0] if len(transports) == 1 else transports,
    }
