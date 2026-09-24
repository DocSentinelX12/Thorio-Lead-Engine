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


def derive_multidimensional_workload_evidence(samples: Any) -> dict[str, Any]:
    """Derive explainable workload/path evidence from explicitly observed dimensions only."""
    if not isinstance(samples, (list, tuple)):
        return {"state": "insufficient_evidence", "sample_count": 0, "workload_combination_count": 0}

    dimension_keys = (
        "workload_class",
        "collective",
        "world_size",
        "message_size_bytes",
        "dtype",
        "reduce_op",
        "algorithm",
        "protocol",
    )
    observed: list[dict[str, Any]] = []
    combinations: dict[str, dict[str, Any]] = {}

    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        evidence = sample.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        signature = evidence.get("workload_signature")
        if not isinstance(signature, Mapping):
            continue
        dimensions = {}
        for key in dimension_keys:
            value = signature.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            if isinstance(value, (str, int, float, bool)):
                dimensions[key] = value
        if not dimensions:
            continue

        measurements: dict[str, Any] = {
            "observed_at": sample.get("observed_at"),
            "success": sample.get("success"),
        }
        for key in ("latency_ms", "bandwidth_gbps"):
            value = sample.get(key)
            if value is not None:
                measurements[key] = value
        entry = {"dimensions": dimensions, **measurements}
        observed.append(entry)

        workload_key = str(evidence.get("workload_key") or "").strip()
        if not workload_key:
            continue
        combination = combinations.setdefault(
            workload_key,
            {
                "workload_key": workload_key,
                "dimensions": dict(sorted(dimensions.items())),
                "sample_count": 0,
                "observations": [],
            },
        )
        # The key is derived from the complete explicit signature, so conflicting
        # dimensions under one key indicate malformed evidence, not a reason to
        # merge or invent a value.
        if combination["dimensions"] != dict(sorted(dimensions.items())):
            combination["inconsistent_evidence"] = True
            continue
        combination["sample_count"] += 1
        combination["observations"].append(entry)

    ordered = tuple(
        {
            **item,
            "observations": tuple(item["observations"]),
        }
        for _, item in sorted(combinations.items())
        if not item.get("inconsistent_evidence")
    )
    return {
        "state": "observed" if ordered else "insufficient_evidence",
        "sample_count": len(samples),
        "workload_combination_count": len(ordered),
        "observed": tuple(observed),
        "by_workload_key": ordered,
    }



def predict_failure_degradation_evidence(samples: Any) -> dict[str, Any]:
    """Derive conservative early-warning evidence from observed route outcomes only."""
    import math

    if not isinstance(samples, (list, tuple)):
        return {"state": "insufficient_evidence", "sample_count": 0}

    valid: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, Mapping) or not isinstance(sample.get("success"), bool):
            continue
        try:
            observed_at = float(sample.get("observed_at"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(observed_at):
            continue
        latency = None
        if sample.get("latency_ms") is not None:
            try:
                parsed = float(sample.get("latency_ms"))
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and math.isfinite(parsed) and parsed > 0:
                latency = parsed
        evidence = sample.get("evidence")
        valid.append({
            "observed_at": observed_at,
            "success": bool(sample["success"]),
            "latency_ms": latency,
            "evidence": dict(evidence) if isinstance(evidence, Mapping) else {},
        })

    valid.sort(key=lambda item: (item["observed_at"], item["success"], item["latency_ms"] is None))
    count = len(valid)
    result: dict[str, Any] = {
        "state": "insufficient_evidence",
        "sample_count": count,
        "success_count": sum(1 for item in valid if item["success"]),
        "failure_count": sum(1 for item in valid if not item["success"]),
    }
    if not valid:
        return result

    consecutive_failures = 0
    for item in reversed(valid):
        if item["success"]:
            break
        consecutive_failures += 1
    consecutive_successes = 0
    for item in reversed(valid):
        if not item["success"]:
            break
        consecutive_successes += 1
    result["consecutive_failures"] = consecutive_failures
    result["consecutive_successes"] = consecutive_successes

    failure_pattern = consecutive_failures >= 2 and count >= 4
    result["failure_pattern"] = failure_pattern

    if count >= 4:
        midpoint = count // 2
        earlier = valid[:midpoint]
        recent = valid[midpoint:]
        earlier_failures = sum(1 for item in earlier if not item["success"])
        recent_failures = sum(1 for item in recent if not item["success"])
        earlier_rate = earlier_failures / len(earlier)
        recent_rate = recent_failures / len(recent)
        result["earlier_failure_rate"] = earlier_rate
        result["recent_failure_rate"] = recent_rate
        result["failure_rate_delta"] = recent_rate - earlier_rate

        latency_values = [item["latency_ms"] for item in valid if item["latency_ms"] is not None]
        latency_deltas = [
            right - left
            for left, right in zip(latency_values, latency_values[1:])
        ]
        latency_degrading = len(latency_values) >= 4 and all(delta > 0 for delta in latency_deltas)
        result["latency_degrading"] = latency_degrading

        if failure_pattern:
            state = "failure_pattern"
        elif recent_rate > earlier_rate or latency_degrading:
            state = "degrading"
        elif result["failure_count"] == 0 and latency_values:
            mean = sum(latency_values) / len(latency_values)
            variance = sum((value - mean) ** 2 for value in latency_values) / len(latency_values)
            coefficient_of_variation = math.sqrt(variance) / mean if mean > 0 else float("inf")
            result["coefficient_of_variation"] = coefficient_of_variation
            if coefficient_of_variation <= 0.10:
                state = "stable"
            else:
                state = "insufficient_evidence"
        else:
            state = "insufficient_evidence"
        result["state"] = state

    result["evidence"] = {
        "first_observed_at": valid[0]["observed_at"],
        "last_observed_at": valid[-1]["observed_at"],
        "observations": tuple(valid),
    }
    explicit_domains = sorted({
        str(item["evidence"].get("failure_domain")).strip()
        for item in valid
        if isinstance(item["evidence"], Mapping)
        and str(item["evidence"].get("failure_domain") or "").strip()
    })
    if explicit_domains:
        result["failure_domains"] = tuple(explicit_domains)
    return result


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
    if latency_count == 0:
        return result

    if latency_count == 1:
        only = valid[0]
        return {
            **result,
            "baseline_latency_ms": only["latency_ms"],
            "recent_latency_ms": only["latency_ms"],
            "trend_delta_ms": None,
            "evidence": {
                "first_observed_at": only["observed_at"],
                "last_observed_at": only["observed_at"],
                "observations": tuple(valid),
            },
        }

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


def derive_continuous_optimization_evidence(candidates: Any) -> dict[str, Any]:
    """Derive deterministic placement adaptation from observed candidate evidence.

    This is deliberately not a synthetic score. It only compares explicit
    observed performance and exact future-capacity preservation supplied by the
    caller. Missing dimensions remain unknown.
    """
    import math

    if not isinstance(candidates, (list, tuple)):
        return {"state": "insufficient_evidence", "candidate_count": 0}

    valid = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_key = str(candidate.get("candidate_key") or "").strip()
        if not candidate_key:
            continue
        item = {
            "candidate_key": candidate_key,
            "observed_latency_ms": None,
            "future_feasible_domain_count": None,
            "future_single_node_count": None,
            "sample_count": int(candidate.get("sample_count", 0) or 0),
        }
        latency = candidate.get("observed_latency_ms")
        if latency is not None:
            try:
                parsed = float(latency)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and math.isfinite(parsed) and parsed > 0:
                item["observed_latency_ms"] = parsed
        for field in ("future_feasible_domain_count", "future_single_node_count"):
            value = candidate.get(field)
            if value is not None:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None and parsed >= 0:
                    item[field] = parsed
        valid.append(item)

    valid.sort(key=lambda item: item["candidate_key"])
    if not valid:
        return {"state": "insufficient_evidence", "candidate_count": 0}

    observed = [item for item in valid if item["observed_latency_ms"] is not None]
    performance_preference = ()
    if observed:
        best_latency = min(float(item["observed_latency_ms"]) for item in observed)
        performance_preference = tuple(
            item["candidate_key"]
            for item in observed
            if float(item["observed_latency_ms"]) == best_latency
        )

    capacity_observed = [
        item for item in valid
        if item["future_feasible_domain_count"] is not None
        or item["future_single_node_count"] is not None
    ]
    capacity_preference = ()
    if capacity_observed:
        max_domain_count = max(
            item["future_feasible_domain_count"]
            if item["future_feasible_domain_count"] is not None else -1
            for item in capacity_observed
        )
        domain_best = [
            item for item in capacity_observed
            if (item["future_feasible_domain_count"] if item["future_feasible_domain_count"] is not None else -1) == max_domain_count
        ]
        max_single_node_count = max(
            item["future_single_node_count"]
            if item["future_single_node_count"] is not None else -1
            for item in domain_best
        )
        capacity_preference = tuple(
            item["candidate_key"]
            for item in domain_best
            if (item["future_single_node_count"] if item["future_single_node_count"] is not None else -1) == max_single_node_count
        )

    balanced = tuple(
        key for key in performance_preference
        if key in set(capacity_preference)
    )
    if balanced:
        state = "balanced"
    elif performance_preference:
        state = "performance_preference"
    elif capacity_preference:
        state = "capacity_preservation"
    else:
        state = "insufficient_evidence"

    return {
        "state": state,
        "candidate_count": len(valid),
        "performance_preference": performance_preference,
        "capacity_preference": capacity_preference,
        "balanced_preference": balanced,
        "candidates": tuple(valid),
    }




def derive_autonomous_closed_loop_evidence(state: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the next control-loop phase from durable, explicit cycle evidence.

    This is a control decision surface, not a second scheduler. It consumes
    observed counts only, never invents performance, capacity, or failure data.
    """
    if not isinstance(state, Mapping):
        return {
            "state": "insufficient_evidence",
            "next_cycle_action": "refresh_and_reconcile",
            "synthetic_values": False,
        }

    def count(name: str) -> int:
        try:
            value = int(state.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    queued = count("queued_tasks")
    leased = count("leased_tasks")
    eligible = count("eligible_resources")
    recovered = count("recovered_expired_tasks")
    requeued = count("requeued_tasks")
    scheduled = count("scheduled_allocations")
    feedback = count("execution_feedback_samples")
    reconciled = count("reconciled_attempts")

    if recovered or requeued:
        phase = "recovery_and_reschedule"
        action = "reconcile_and_reschedule"
    elif scheduled:
        phase = "executing"
        action = "await_execution_feedback"
    elif feedback:
        phase = "feedback_available"
        action = "reuse_observed_feedback"
    elif queued and eligible:
        phase = "ready_to_schedule"
        action = "refresh_and_schedule"
    elif queued and not eligible:
        phase = "awaiting_capacity"
        action = "refresh_and_reconcile"
    elif leased:
        phase = "awaiting_execution"
        action = "await_execution_feedback"
    else:
        phase = "idle"
        action = "refresh_and_reconcile"

    return {
        "state": phase,
        "next_cycle_action": action,
        "queued_tasks": queued,
        "leased_tasks": leased,
        "eligible_resources": eligible,
        "recovered_expired_tasks": recovered,
        "requeued_tasks": requeued,
        "scheduled_allocations": scheduled,
        "reconciled_attempts": reconciled,
        "execution_feedback_samples": feedback,
        "feedback_is_durable": True,
        "placement_recomputed_from_current_inventory": True,
        "hard_validation_remains_authoritative": True,
        "compute_allocation_remains_authoritative": True,
        "synthetic_values": False,
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
    result["predictive_failure_degradation"] = predict_failure_degradation_evidence(samples)

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
        result["predictive_failure_by_workload_key"] = {
            key: predict_failure_degradation_evidence(items)
            for key, items in sorted(workload_samples.items())
        }
        multidimensional = derive_multidimensional_workload_evidence(samples)
        result["multidimensional_by_workload_key"] = {
            item["workload_key"]: item
            for item in multidimensional["by_workload_key"]
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
            workload_signature = metric.get("workload_signature")
            if isinstance(workload_signature, Mapping) and workload_signature:
                evidence["workload_signature"] = dict(workload_signature)
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
