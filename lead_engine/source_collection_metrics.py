"""Persistent source-level collection yield telemetry."""
from __future__ import annotations

from typing import Any, Dict, Mapping

_STATE_KEY = "source_collection_metrics"
_REQUIRED_COUNTS = ("discovered_count", "accepted_count", "duplicate_count", "failed_count")


def _count(result: Mapping[str, Any], key: str) -> int:
    if key not in result:
        raise ValueError(f"Collection result requires {key}.")
    value = result[key]
    if isinstance(value, bool):
        raise ValueError(f"Collection result {key} must be a non-negative integer.")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Collection result {key} must be a non-negative integer.") from exc
    if value < 0:
        raise ValueError(f"Collection result {key} must be a non-negative integer.")
    return value


def _rates(metrics: Dict[str, Any]) -> Dict[str, Any]:
    discovered = metrics["discovered"]
    metrics["acceptance_rate"] = metrics["accepted"] / discovered if discovered else 0.0
    metrics["duplicate_rate"] = metrics["duplicates"] / discovered if discovered else 0.0
    metrics["failure_rate"] = metrics["failed"] / discovered if discovered else 0.0
    return metrics


def source_collection_metrics(db: Any) -> Dict[str, Dict[str, Any]]:
    state = db.get_state(_STATE_KEY)
    if state is None:
        return {}
    if not isinstance(state, dict):
        raise ValueError("Source collection metrics state is corrupt.")
    result = {}
    for source, metrics in state.items():
        if not isinstance(source, str) or not isinstance(metrics, dict):
            raise ValueError("Source collection metrics state is corrupt.")
        result[source] = _rates(dict(metrics))
    return result


def record_source_collection_metrics(
    db: Any,
    source_name: str,
    collection_result: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError("Source name is required.")
    if not isinstance(collection_result, Mapping):
        raise ValueError("Collection result must be an object.")

    counts = {key: _count(collection_result, key) for key in _REQUIRED_COUNTS}
    state = source_collection_metrics(db)
    current = state.get(source_name.strip(), {
        "runs": 0,
        "discovered": 0,
        "accepted": 0,
        "duplicates": 0,
        "failed": 0,
    })
    current["runs"] += 1
    current["discovered"] += counts["discovered_count"]
    current["accepted"] += counts["accepted_count"]
    current["duplicates"] += counts["duplicate_count"]
    current["failed"] += counts["failed_count"]
    current = _rates(current)
    state[source_name.strip()] = current
    db.set_state(_STATE_KEY, state)
    return current
