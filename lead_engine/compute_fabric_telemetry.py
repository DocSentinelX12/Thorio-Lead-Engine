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
    normalized = {str(key): path[key] for key in ("node_id", "gpu_uuid", "nic", "nic_pci_bus_id", "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer") if path.get(key) is not None and str(path.get(key)).strip() != ""}
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
    allowed = ("workload_class", "collective", "world_size", "message_size_bytes", "dtype", "reduce_op", "algorithm", "protocol")
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
        try:
            elapsed_ms = float(probe.get("all_reduce_elapsed_ms"))
        except (TypeError, ValueError):
            continue
        if elapsed_ms <= 0:
            continue
        gpu_binding = item.get("gpu_binding")
        physical_path = gpu_binding.get("planned_physical_path") if isinstance(gpu_binding, Mapping) else None
        path = physical_path if isinstance(physical_path, Mapping) else {}
        observed_paths = gpu_binding.get("observed_fabric_paths") if isinstance(gpu_binding, Mapping) else None
        if not isinstance(observed_paths, (list, tuple)):
            observed_paths = ()
        observed_path_id = str(gpu_binding.get("observed_fabric_path_id") or "").strip() if isinstance(gpu_binding, Mapping) else ""
        metrics.append({"rank": int(item.get("rank", probe.get("rank", -1))), "gpu_uuid": str(probe.get("gpu_uuid") or "").strip(), "node_id": str(gpu_binding.get("node_id") or "").strip() if isinstance(gpu_binding, Mapping) else "", "transport": str(probe.get("network_transport") or "").strip() or None, "all_reduce_elapsed_ms": elapsed_ms, "physical_path": dict(path), "path_key": physical_path_key(path), "fabric_path_id": observed_path_id, "observed_fabric_paths": tuple(dict(item) for item in observed_paths if isinstance(item, Mapping)), "placement_id": str(verification.get("placement_id") or "").strip(), "execution_attempt_id": str(verification.get("execution_attempt_id") or verification.get("attempt_id") or "").strip(), "generation": verification.get("generation"), "workload_signature": dict(workload_signature), "workload_key": workload_performance_key(path, workload_signature) if workload_signature else ""})
    return tuple(sorted(metrics, key=lambda item: (int(item["rank"]), str(item["gpu_uuid"]))))


def aggregate_execution_metrics(metrics: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Aggregate only observed rank measurements for one execution."""
    if not metrics:
        return {"sample_count": 0}
    values = [float(item["all_reduce_elapsed_ms"]) for item in metrics]
    transports = sorted({str(item["transport"]) for item in metrics if item.get("transport")})
    return {"sample_count": len(values), "min_all_reduce_elapsed_ms": min(values), "max_all_reduce_elapsed_ms": max(values), "avg_all_reduce_elapsed_ms": sum(values) / len(values), "transport": transports[0] if len(transports) == 1 else transports}


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
    serialized = json.dumps({"path_key": path_key, "workload": normalized_workload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def predict_route_evidence(samples: Any) -> dict[str, Any]:
    """Derive conservative temporal route evidence from observed latency only."""
    import math

    if not isinstance(samples, (list, tuple)):
        return {"state": "insufficient_evidence", "sample_count": 0, "latency_sample_count": 0}

    valid = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        try:
            observed_at = float(sample.get("observed_at"))
            latency = float(sample.get("latency_ms"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(observed_at) or not math.isfinite(latency) or latency <= 0:
            continue
        evidence = sample.get("evidence")
        valid.append({
            "observed_at": observed_at,
            "latency_ms": latency,
            "evidence": dict(evidence) if isinstance(evidence, Mapping) else {},
        })

    valid.sort(key=lambda item: (item["observed_at"], item["latency_ms"]))
    latency_count = len(valid)
    result = {
        "state": "insufficient_evidence",
        "sample_count": len(samples),
        "latency_sample_count": latency_count,
    }
    if latency_count < 2:
        return result

    midpoint = latency_count // 2
    baseline = valid[:midpoint]
    recent = valid[midpoint:]
    baseline_latency = sum(item["latency_ms"] for item in baseline) / len(baseline)
    recent_latency = sum(item["latency_ms"] for item in recent) / len(recent)
    trend_delta = recent_latency - baseline_latency

    values = [item["latency_ms"] for item in valid]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    coefficient_of_variation = math.sqrt(variance) / mean if mean > 0 else float("inf")
    deltas = [
        right["latency_ms"] - left["latency_ms"]
        for left, right in zip(valid, valid[1:])
    ]

    if latency_count < 4:
        state = "insufficient_evidence"
    elif all(delta > 0 for delta in deltas) and trend_delta > 0:
        state = "degrading"
    elif all(delta < 0 for delta in deltas) and trend_delta < 0:
        state = "improving"
    elif coefficient_of_variation <= 0.10:
        state = "stable"
    else:
        state = "insufficient_evidence"

    return {
        "state": state,
        "sample_count": len(samples),
        "latency_sample_count": latency_count,
        "baseline_latency_ms": baseline_latency,
        "recent_latency_ms": recent_latency,
        "trend_delta_ms": trend_delta,
        "coefficient_of_variation": coefficient_of_variation,
        "evidence": {
            "first_observed_at": valid[0]["observed_at"],
            "last_observed_at": valid[-1]["observed_at"],
            "observations": tuple(valid),
        },
    }


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
        try:
            timestamp = float(sample.get("observed_at"))
        except (TypeError, ValueError):
            timestamp = float("-inf")
        valid.append((timestamp, parsed_latency, success))
    if not valid:
        return {"sample_count": 0, "success_count": 0, "failure_count": 0}
    valid.sort(key=lambda item: item[0])
    latencies = [item[1] for item in valid if item[1] is not None]
    latest_latency = next((item[1] for item in reversed(valid) if item[1] is not None), None)
    latest_observed_at = valid[-1][0] if valid[-1][0] != float("-inf") else None
    latest_success = valid[-1][2]
    failure_count = sum(1 for item in valid if not item[2])
    result = {"sample_count": len(valid), "success_count": len(valid) - failure_count, "failure_count": failure_count, "failure_rate": failure_count / len(valid), "latest_observed_at": latest_observed_at, "latest_success": latest_success}
    if latencies:
        mean = sum(latencies) / len(latencies)
        previous_latency = latencies[-2] if len(latencies) >= 2 else None
        result.update({"latest_latency_ms": latest_latency, "historical_mean_latency_ms": mean, "latency_delta_from_mean_ms": latest_latency - mean if latest_latency is not None else None, "latency_change_from_previous_ms": latest_latency - previous_latency if latest_latency is not None and previous_latency is not None else None, "latency_change_ratio": ((latest_latency / previous_latency) - 1.0) if latest_latency is not None and previous_latency not in (None, 0) else None})
    consecutive_failures = 0
    for _, _, success in reversed(valid):
        if success:
            break
        consecutive_failures += 1
    consecutive_successes = 0
    for _, _, success in reversed(valid):
        if not success:
            break
        consecutive_successes += 1
    result["consecutive_failures"] = consecutive_failures
    result["consecutive_successes"] = consecutive_successes

    workload_samples: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        evidence = sample.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        workload_key = str(evidence.get("workload_key") or "").strip()
        if not workload_key:
            continue
        workload_samples.setdefault(workload_key, []).append(dict(sample))
    if workload_samples:
        result["predictive_by_workload_key"] = {
            key: predict_route_evidence(items)
            for key, items in sorted(workload_samples.items())
        }
    return result


def reconcile_post_rebind_runtime(
    rebind: Mapping[str, Any] | None,
    observations: Any,
) -> dict[str, Any]:
    """Prove that a recovered generation actually used its selected standby."""
    if not isinstance(rebind, Mapping) or not str(rebind.get("to_path_id") or "").strip():
        return {"required": False, "converged": True, "reason": "no_pending_rebind"}
    expected = str(rebind.get("to_path_id") or "").strip()
    observed = []
    for item in observations if isinstance(observations, (list, tuple)) else ():
        if not isinstance(item, Mapping):
            continue
        path_id = str(item.get("fabric_path_id") or "").strip()
        if path_id:
            observed.append(path_id)
    unique = tuple(dict.fromkeys(observed))
    return {
        "required": True,
        "converged": expected in unique,
        "expected_path_id": expected,
        "observed_path_ids": unique,
        "reason": "selected_standby_observed" if expected in unique else "selected_standby_not_observed",
    }


def extract_execution_path_observations(
    verification: Mapping[str, Any],
    *,
    observed_at: float,
) -> tuple[dict[str, Any], ...]:
    """Convert only exact-path workload observations into route-health evidence."""
    metrics = extract_execution_metrics(verification)
    observations: list[dict[str, Any]] = []
    for metric in metrics:
        elapsed_ms = float(metric["all_reduce_elapsed_ms"])
        observed_paths = metric.get("observed_fabric_paths") or ()
        if not isinstance(observed_paths, (list, tuple)):
            observed_paths = ()
        if not observed_paths:
            single = str(metric.get("fabric_path_id") or "").strip()
            observed_paths = ({"fabric_path_id": single},) if single else ()
        for observed_path in observed_paths:
            if not isinstance(observed_path, Mapping):
                continue
            fabric_path_id = str(observed_path.get("fabric_path_id") or "").strip()
            if not fabric_path_id:
                continue
            evidence = {
                "source": "observed_all_reduce",
                "placement_id": str(metric.get("placement_id") or ""),
                "execution_attempt_id": str(metric.get("execution_attempt_id") or ""),
                "generation": metric.get("generation"),
                "rank": int(metric["rank"]),
                "gpu_uuid": str(metric.get("gpu_uuid") or ""),
                "network_transport": metric.get("transport"),
            }
            workload_key = str(metric.get("workload_key") or "").strip()
            if workload_key:
                evidence["workload_key"] = workload_key
            if observed_path.get("destination_rank") is not None:
                evidence["destination_rank"] = observed_path.get("destination_rank")
            if observed_path.get("destination_gpu") is not None:
                evidence["destination_gpu"] = observed_path.get("destination_gpu")
            observations.append({
                "fabric_path_id": fabric_path_id,
                "latency_us": elapsed_ms * 1000.0,
                "success": True,
                "observed_at": float(observed_at),
                "evidence": evidence,
            })
    return tuple(observations)
