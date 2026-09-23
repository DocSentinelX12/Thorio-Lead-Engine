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


def extract_workload_signature(verification: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only workload descriptors explicitly present in execution evidence."""
    candidates = []
    for key in ("workload", "fabric_workload", "workload_signature"):
        value = verification.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    for item in verification.get("process_evidence", []) if isinstance(verification.get("process_evidence"), list) else []:
        if not isinstance(item, Mapping):
            continue
        probe = item.get("probe")
        if isinstance(probe, Mapping):
            candidates.append(probe)
    allowed = (
        "workload_class", "collective", "world_size", "message_size_bytes",
        "dtype", "reduce_op", "algorithm", "protocol",
    )
    result = {}
    for candidate in candidates:
        for key in allowed:
            value = candidate.get(key)
            if value is not None and (not isinstance(value, str) or value.strip()):
                result[key] = value.strip() if isinstance(value, str) else value
    return result


def extract_execution_metrics(verification: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one metric record per rank with an observed all-reduce duration."""
    process_evidence = verification.get("process_evidence")
    if not isinstance(process_evidence, list):
        return ()
    workload_signature = extract_workload_signature(verification)

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
            "workload_signature": dict(workload_signature),
            "workload_key": workload_performance_key(path, workload_signature),
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


def workload_performance_key(path: Mapping[str, Any], workload: Mapping[str, Any]) -> str:
    """Return a deterministic identity for observed performance of one path and workload."""
    path_key = physical_path_key(path)
    if not path_key:
        return ""
    normalized_workload = {}
    for key, value in workload.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if isinstance(value, (str, int, float, bool)):
            normalized_workload[str(key)] = value
    if not normalized_workload:
        return path_key
    serialized = json.dumps(
        {"path_key": path_key, "workload": normalized_workload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def summarize_route_health(samples: Any) -> dict[str, Any]:
    """Summarize observed route outcomes without applying a health threshold."""
    if not isinstance(samples, (list, tuple)):
        return {"sample_count": 0, "success_count": 0, "failure_count": 0}
    valid = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        success = sample.get("success")
        if not isinstance(success, bool):
            continue
        latency = sample.get("latency_ms")
        parsed_latency = None
        if latency is not None:
            try:
                parsed_latency = float(latency)
            except (TypeError, ValueError):
                parsed_latency = None
            if parsed_latency is not None and parsed_latency <= 0:
                parsed_latency = None
        observed_at = sample.get("observed_at")
        try:
            timestamp = float(observed_at)
        except (TypeError, ValueError):
            timestamp = float("-inf")
        valid.append((timestamp, parsed_latency, success))
    if not valid:
        return {"sample_count": 0, "success_count": 0, "failure_count": 0}
    valid.sort(key=lambda item: item[0])
    latencies = [item[1] for item in valid if item[1] is not None]
    latest_latency = next((item[1] for item in reversed(valid) if item[1] is not None), None)
    result = {
        "sample_count": len(valid),
        "success_count": sum(1 for item in valid if item[2]),
        "failure_count": sum(1 for item in valid if not item[2]),
    }
    if latencies:
        mean = sum(latencies) / len(latencies)
        result.update({
            "latest_latency_ms": latest_latency,
            "historical_mean_latency_ms": mean,
            "latency_delta_from_mean_ms": (
                latest_latency - mean if latest_latency is not None else None
            ),
        })
    result["failure_rate"] = result["failure_count"] / result["sample_count"]
    return result
