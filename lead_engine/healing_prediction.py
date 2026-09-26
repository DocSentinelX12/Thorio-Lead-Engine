"""Predictive signal discovery and failure-risk intelligence for autonomous healing."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from typing import Any, Mapping

from .healing_evidence import HealingEvidenceGraph


class PredictiveHealingError(RuntimeError):
    pass


class PredictiveHealingIntelligence:
    """Learns path-scoped signals from immutable evidence without becoming authority."""

    MIN_CLASS_SAMPLES = 2
    MIN_TOTAL_SAMPLES = 4

    def __init__(self, *, graph: HealingEvidenceGraph, db_path: str = ":memory__"):
        self.graph = graph
        self.db_path = db_path
        self._memory = sqlite3.connect(":memory:") if db_path == ":memory:" else None
        if self._memory:
            self._memory.row_factory = sqlite3.Row
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS predictive_signal_models(
              scope_id TEXT NOT NULL,
              signal TEXT NOT NULL,
              model_json TEXT NOT NULL,
              updated_at REAL NOT NULL,
              PRIMARY KEY(scope_id,signal)
            );
            CREATE TABLE IF NOT EXISTS predictive_assessments(
              assessment_id TEXT PRIMARY KEY,
              scope_id TEXT NOT NULL,
              observed_at REAL NOT NULL,
              assessment_json TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_predictive_assessments_scope
              ON predictive_assessments(scope_id,observed_at);
            """)

    def _connect(self):
        if self._memory:
            return self._memory
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _flatten(value: Any, prefix: str = "") -> dict[str, float]:
        result: dict[str, float] = {}
        if isinstance(value, Mapping):
            for key, item in value.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                result.update(PredictiveHealingIntelligence._flatten(item, name))
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            if prefix and not prefix.endswith(("observed_at", "created_at", "updated_at", "recorded_at")):
                result[prefix] = float(value)
        return result

    @staticmethod
    def _failed(observation: Mapping[str, Any]) -> bool:
        payload = observation.get("payload") or {}
        state = str(payload.get("state") or "").upper()
        status = str(payload.get("measurement_status") or payload.get("status") or "").lower()
        return state in {"FAILED", "DEGRADED", "UNAVAILABLE"} or status in {"failed", "unavailable", "error"} or payload.get("verified") is False

    @staticmethod
    def _mean(values):
        return sum(values) / len(values) if values else None

    @staticmethod
    def _std(values):
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))

    @staticmethod
    def _effect(healthy, failed):
        hm, fm = PredictiveHealingIntelligence._mean(healthy), PredictiveHealingIntelligence._mean(failed)
        if hm is None or fm is None:
            return 0.0
        hs, fs = PredictiveHealingIntelligence._std(healthy), PredictiveHealingIntelligence._std(failed)
        pooled = math.sqrt((hs * hs + fs * fs) / 2.0)
        if pooled == 0:
            return 1.0 if fm != hm else 0.0
        return max(-1.0, min(1.0, (fm - hm) / pooled))

    def discover(self, *, scope_id: str) -> dict[str, Any]:
        observations = self.graph.observations(scope_id=scope_id)
        signals: dict[str, dict[str, Any]] = {}
        for obs in observations:
            values = self._flatten(obs.get("payload") or {})
            failed = self._failed(obs)
            for signal, value in values.items():
                entry = signals.setdefault(signal, {"healthy": [], "failed": [], "observation_ids": []})
                entry["failed" if failed else "healthy"].append(value)
                entry["observation_ids"].append(obs["observation_id"])
        models = []
        now = time.time()
        with self._connect() as db:
            for signal in sorted(signals):
                entry = signals[signal]
                healthy, failed = entry["healthy"], entry["failed"]
                predictive = len(healthy) >= self.MIN_CLASS_SAMPLES and len(failed) >= self.MIN_CLASS_SAMPLES
                model = {
                    "scope_id": scope_id,
                    "signal": signal,
                    "healthy_samples": len(healthy),
                    "failed_samples": len(failed),
                    "healthy_mean": self._mean(healthy),
                    "healthy_std": self._std(healthy),
                    "failed_mean": self._mean(failed),
                    "failed_std": self._std(failed),
                    "effect": self._effect(healthy, failed),
                    "predictive": predictive,
                    "observation_ids": tuple(entry["observation_ids"]),
                }
                db.execute(
                    """INSERT INTO predictive_signal_models(scope_id,signal,model_json,updated_at)
                       VALUES(?,?,?,?) ON CONFLICT(scope_id,signal) DO UPDATE SET
                       model_json=excluded.model_json,updated_at=excluded.updated_at""",
                    (scope_id, signal, json.dumps(model, sort_keys=True, default=list), now),
                )
                if predictive:
                    models.append(model)
        return {
            "scope_id": scope_id,
            "signals": tuple(models),
            "discovered_signal_count": len(signals),
            "predictive_signal_count": len(models),
        }

    def _models(self, scope_id: str):
        with self._connect() as db:
            rows = db.execute(
                "SELECT model_json FROM predictive_signal_models WHERE scope_id=? ORDER BY signal",
                (scope_id,),
            ).fetchall()
        return tuple(json.loads(row["model_json"]) for row in rows)

    def predict(self, *, scope_id: str, observed_at: float | None = None) -> dict[str, Any]:
        observations = self.graph.observations(scope_id=scope_id)
        if not observations:
            return {"scope_id": scope_id, "state": "INSUFFICIENT_EVIDENCE", "confidence": 0.0, "failure_risk": None, "signals": (), "source_observation_ids": ()}
        self.discover(scope_id=scope_id)
        models = self._models(scope_id)
        latest = max(observations, key=lambda x: (float(x["observed_at"]), x["observation_id"]))
        values = self._flatten(latest.get("payload") or {})
        contributions = []
        for model in models:
            if model["signal"] not in values:
                continue
            healthy_mean = model["healthy_mean"]
            healthy_std = model["healthy_std"]
            if healthy_mean is None:
                continue
            scale = max(float(healthy_std or 0.0), abs(float(healthy_mean)) * 0.05, 1e-9)
            deviation = (values[model["signal"]] - healthy_mean) / scale
            direction = 1.0 if model["effect"] > 0 else -1.0
            contribution = max(-1.0, min(1.0, deviation * direction * abs(float(model["effect"]))))
            contributions.append({
                "signal": model["signal"],
                "value": values[model["signal"]],
                "healthy_mean": healthy_mean,
                "effect": model["effect"],
                "contribution": contribution,
                "source_observation_ids": tuple(model["observation_ids"]),
            })
        if len(observations) < self.MIN_TOTAL_SAMPLES or not models:
            result = {
                "scope_id": scope_id, "state": "INSUFFICIENT_EVIDENCE", "confidence": min(1.0, len(observations) / self.MIN_TOTAL_SAMPLES),
                "failure_risk": None, "signals": tuple(contributions),
                "source_observation_ids": tuple(o["observation_id"] for o in observations),
                "latest_observed_at": float(latest["observed_at"]),
            }
        else:
            raw = sum(max(0.0, c["contribution"]) for c in contributions)
            risk = 1.0 - math.exp(-raw)
            confidence = min(1.0, len(models) / 4.0) * min(1.0, len(observations) / 8.0)
            result = {
                "scope_id": scope_id, "state": "PREDICTED", "confidence": round(confidence, 6),
                "failure_risk": round(risk, 6), "signals": tuple(contributions),
                "source_observation_ids": tuple(o["observation_id"] for o in observations),
                "latest_observed_at": float(latest["observed_at"]),
            }
        if observed_at is not None:
            result["assessment_observed_at"] = float(observed_at)
        material = json.dumps(result, sort_keys=True, default=list)
        assessment_id = "prediction:" + hashlib.sha256(f"{scope_id}\0{material}".encode()).hexdigest()
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO predictive_assessments VALUES(?,?,?,?,?)",
                (assessment_id, scope_id, float(result.get("latest_observed_at", time.time())), material, time.time()),
            )
        result["assessment_id"] = assessment_id
        return result

    def counterfactual(self, *, scope_id: str) -> dict[str, Any]:
        prediction = self.predict(scope_id=scope_id)
        if prediction["state"] != "PREDICTED":
            return {"scope_id": scope_id, "state": "INSUFFICIENT_EVIDENCE", "counterfactuals": ()}
        deltas = []
        for signal in prediction["signals"]:
            contribution = float(signal["contribution"])
            baseline = max(0.0, contribution)
            deltas.append({
                "signal": signal["signal"],
                "observed_value": signal["value"],
                "healthy_baseline": signal["healthy_mean"],
                "risk_delta_if_baseline": round(-baseline, 6),
                "source_observation_ids": signal["source_observation_ids"],
            })
        return {
            "scope_id": scope_id,
            "state": "COUNTERFACTUAL_ANALYSIS",
            "current_failure_risk": prediction["failure_risk"],
            "counterfactuals": tuple(deltas),
            "assessment_id": prediction["assessment_id"],
        }
