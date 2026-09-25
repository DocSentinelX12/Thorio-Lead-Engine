"""Evidence-backed intelligence for repeated active GPU fabric measurements.

The module never creates a performance baseline from unrelated hardware, missing
measurements, or unverified executions. A baseline belongs to one exact physical
fabric path and one observed endpoint/direction identity.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence


class ActivePathIntelligence:
    """Analyze repeated active GDRDMA observations for one exact path."""

    _IDENTITY_FIELDS = (
        "worker_id",
        "remote_worker_id",
        "remote_endpoint",
        "direction",
        "gpu_uuid",
        "rdma_device",
        "rdma_port",
    )

    @classmethod
    def _identity(cls, measurement: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        values = []
        for field in cls._IDENTITY_FIELDS:
            value = measurement.get(field)
            if value is None or str(value).strip() == "":
                continue
            values.append((field, str(value).strip()))
        return tuple(values)

    @classmethod
    def _measured(cls, samples: Sequence[Mapping[str, Any]], path_id: str) -> list[dict[str, Any]]:
        rows = []
        for sample in samples:
            if not isinstance(sample, Mapping):
                continue
            if str(sample.get("path_id") or "").strip() != path_id:
                continue
            measurement = sample.get("measurement")
            if not isinstance(measurement, Mapping):
                continue
            if str(measurement.get("measurement_status") or "").strip().lower() != "measured":
                continue
            if measurement.get("verified") is not True:
                continue
            try:
                observed_at = float(sample.get("observed_at"))
                bandwidth = float(measurement.get("bandwidth_gbps"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(observed_at) or not math.isfinite(bandwidth) or bandwidth <= 0:
                continue
            rows.append({
                "path_id": path_id,
                "observed_at": observed_at,
                "bandwidth_gbps": bandwidth,
                "identity": cls._identity(measurement),
                "measurement": dict(measurement),
            })
        return sorted(rows, key=lambda row: (row["observed_at"], str(row["identity"])))

    @staticmethod
    def _identity_map(identity: tuple[tuple[str, str], ...]) -> dict[str, str]:
        return {key: value for key, value in identity}

    @classmethod
    def _canonical_identity(cls, rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str], ...]:
        if not rows:
            return ()
        counts = Counter(tuple(row.get("identity") or ()) for row in rows)
        return max(counts, key=lambda identity: (counts[identity], max(float(row["observed_at"]) for row in rows if tuple(row.get("identity") or ()) == identity)))

    @classmethod
    def analyze(cls, samples: Sequence[Mapping[str, Any]], *, path_id: str) -> dict[str, Any]:
        path_id = str(path_id or "").strip()
        if not path_id:
            raise ValueError("path_id is required")

        all_rows = [sample for sample in samples if isinstance(sample, Mapping)] if isinstance(samples, Sequence) else []
        path_rows = [sample for sample in all_rows if str(sample.get("path_id") or "").strip() == path_id]
        measured_rows = cls._measured(path_rows, path_id)
        canonical_identity = cls._canonical_identity(measured_rows)
        comparable = [row for row in measured_rows if tuple(row["identity"]) == canonical_identity]
        comparable.sort(key=lambda row: row["observed_at"])

        identity_map = cls._identity_map(canonical_identity)
        failed_observations = []
        for sample in path_rows:
            measurement = sample.get("measurement")
            if not isinstance(measurement, Mapping):
                continue
            status = str(measurement.get("measurement_status") or "").strip().lower()
            if status in {"failed", "unavailable"} or measurement.get("verified") is False:
                try:
                    observed_at = float(sample.get("observed_at"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(observed_at):
                    failed_observations.append({"observed_at": observed_at, "measurement": dict(measurement)})
        failed_observations.sort(key=lambda item: item["observed_at"])

        latest = comparable[-1] if comparable else None
        baseline_rows = comparable[:-1] if len(comparable) >= 2 else []
        baseline = None
        bandwidth_delta = None
        bandwidth_change_ratio = None
        variability = {"sample_count": len(baseline_rows), "coefficient_of_variation": None}
        state = "insufficient_evidence"

        if baseline_rows:
            values = [float(row["bandwidth_gbps"]) for row in baseline_rows]
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            standard_deviation = math.sqrt(variance)
            variability = {
                "sample_count": len(values),
                "mean_bandwidth_gbps": mean,
                "standard_deviation_gbps": standard_deviation,
                "coefficient_of_variation": standard_deviation / mean if mean > 0 else None,
            }
            baseline = {
                "sample_count": len(values),
                "bandwidth_gbps": mean,
                "first_observed_at": baseline_rows[0]["observed_at"],
                "last_observed_at": baseline_rows[-1]["observed_at"],
            }

        if latest is not None and baseline is not None:
            latest_bandwidth = float(latest["bandwidth_gbps"])
            bandwidth_delta = latest_bandwidth - float(baseline["bandwidth_gbps"])
            bandwidth_change_ratio = bandwidth_delta / float(baseline["bandwidth_gbps"]) if baseline["bandwidth_gbps"] else None
            if len(comparable) >= 4 and variability["coefficient_of_variation"] is not None and variability["coefficient_of_variation"] > 0.10 and abs(bandwidth_change_ratio or 0.0) < 0.10:
                state = "unstable"
            elif bandwidth_change_ratio is not None and bandwidth_change_ratio < 0 and latest_bandwidth < min(float(row["bandwidth_gbps"]) for row in baseline_rows):
                state = "degrading"
            else:
                state = "stable"

        latest_path_observations = sorted(path_rows, key=lambda sample: float(sample.get("observed_at", float("-inf"))) if str(sample.get("observed_at") or "").strip() else float("-inf"))
        latest_raw = latest_path_observations[-1] if latest_path_observations else None
        latest_measurement = latest_raw.get("measurement") if isinstance(latest_raw, Mapping) else None
        if isinstance(latest_measurement, Mapping):
            latest_status = str(latest_measurement.get("measurement_status") or "").strip().lower()
            if latest_status in {"failed", "unavailable"} or latest_measurement.get("verified") is False:
                state = "failed"

        prior_failure = bool(failed_observations and latest is not None and failed_observations[-1]["observed_at"] < latest["observed_at"])
        if prior_failure and latest is not None and len([row for row in comparable if row["observed_at"] > failed_observations[-1]["observed_at"]]) >= 2:
            state = "recovered"

        return {
            "path_id": path_id,
            "state": state,
            "comparable_sample_count": len(comparable),
            "total_path_observation_count": len(path_rows),
            "baseline": baseline,
            "latest": {
                "observed_at": latest["observed_at"],
                "bandwidth_gbps": latest["bandwidth_gbps"],
            } if latest is not None else None,
            "bandwidth_delta_gbps": bandwidth_delta,
            "bandwidth_change_ratio": bandwidth_change_ratio,
            "variability": variability,
            "endpoint_identity": identity_map,
            "failure_or_connectivity_failure": state == "failed",
            "recovery": {
                "prior_failure_observed": prior_failure,
                "latest_measurement_verified": bool(latest is not None),
                "failure_observed_at": failed_observations[-1]["observed_at"] if failed_observations else None,
            },
            "synthetic_baseline": False,
            "evidence": {
                "measured_observations": tuple({"observed_at": row["observed_at"], "bandwidth_gbps": row["bandwidth_gbps"], "identity": dict(row["identity"])} for row in comparable),
                "failed_observations": tuple(failed_observations),
            },
        }
