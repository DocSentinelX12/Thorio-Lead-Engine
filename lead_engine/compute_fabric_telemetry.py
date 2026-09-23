"""Evidence-only execution telemetry for the GPU fabric.

This module extracts measurements already observed by the distributed runtime.
It never invents performance values, health scores, or scheduling policy.
"""

from __future__ import annotations

from typing import Any, Mapping


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
        metrics.append({
            "rank": int(item.get("rank", probe.get("rank", -1))),
            "gpu_uuid": str(probe.get("gpu_uuid") or "").strip(),
            "node_id": str(item.get("gpu_binding", {}).get("node_id") or "").strip()
                if isinstance(item.get("gpu_binding"), Mapping) else "",
            "transport": str(probe.get("network_transport") or "").strip() or None,
            "all_reduce_elapsed_ms": elapsed_ms,
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
