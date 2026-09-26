"""Evidence-governed unified control plane for the GPU fabric.

This layer coordinates intelligence; it does not become an authority for physical
truth. Exact physical identity, verification, active measurements, route health,
placement, and recovery remain authoritative in their existing layers.

The control plane provides durable evidence lineage, adaptive action-risk gates,
champion/challenger strategy governance, capability preservation, counterfactual
records, and closed-loop outcomes. No strategy can be promoted unless a proven
incumbent remains continuously available until the replacement has demonstrated
sustained contextual superiority and an independently verified availability floor.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_ACTION_RISK = {"route": 1, "placement": 2, "migration": 3, "recovery": 3, "experiment": 2}
_ACTION_STATES = {"proposed", "authorized", "executing", "succeeded", "rejected", "rolled_back", "expired"}


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: str
    kind: str
    subject: str
    observed_at: float
    payload: dict[str, Any]
    confidence: float
    provenance: str


@dataclass(frozen=True)
class ActionDecision:
    decision_id: str
    action: str
    risk_level: int
    authorized: bool
    confidence: float
    independent_source_count: int
    required_source_count: int
    evidence_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class StrategyDecision:
    strategy_id: str
    capability: str
    role: str
    eligible: bool
    reason: str


class UnifiedControlPlane:
    """Durable closed-loop intelligence coordinator.

    Inputs are immutable observations from authoritative subsystems. The control
    plane can reason over those observations and authorize policy-level actions,
    but cannot certify physical state or bypass lower-layer gates.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS control_evidence (
                evidence_id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
                subject TEXT NOT NULL, observed_at REAL NOT NULL, payload_json TEXT NOT NULL,
                confidence REAL NOT NULL, provenance TEXT NOT NULL, recorded_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS control_decisions (
                decision_id TEXT PRIMARY KEY, action TEXT NOT NULL, risk_level INTEGER NOT NULL,
                authorized INTEGER NOT NULL, confidence REAL NOT NULL, independent_sources INTEGER NOT NULL,
                required_sources INTEGER NOT NULL, evidence_ids_json TEXT NOT NULL, reason TEXT NOT NULL,
                created_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS control_outcomes (
                outcome_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, strategy_id TEXT,
                outcome TEXT NOT NULL, observed_at REAL NOT NULL, metrics_json TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL, recorded_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS control_strategies (
                strategy_id TEXT PRIMARY KEY, capability TEXT NOT NULL, role TEXT NOT NULL,
                status TEXT NOT NULL, version INTEGER NOT NULL, created_at REAL NOT NULL,
                promoted_at REAL, demoted_at REAL, retired_at REAL, availability REAL NOT NULL DEFAULT 1.0,
                evidence_json TEXT NOT NULL, metadata_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS control_strategy_observations (
                observation_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, capability TEXT NOT NULL,
                success INTEGER NOT NULL, performance REAL, safety_ok INTEGER NOT NULL,
                observed_at REAL NOT NULL, evidence_ids_json TEXT NOT NULL, metadata_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS control_capabilities (
                capability TEXT PRIMARY KEY, incumbent_strategy_id TEXT, fallback_strategy_id TEXT,
                minimum_availability REAL NOT NULL, minimum_reliability REAL NOT NULL,
                updated_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS control_counterfactuals (
                counterfactual_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
                expected_outcome_json TEXT NOT NULL, confidence REAL NOT NULL, evidence_ids_json TEXT NOT NULL,
                created_at REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_control_evidence_subject ON control_evidence(subject,observed_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_control_decisions_action ON control_decisions(action,created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_control_strategy_obs ON control_strategy_observations(strategy_id,observed_at)")
            db.commit()

    @staticmethod
    def _id(prefix: str, payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"{prefix}:{hashlib.sha256(canonical.encode()).hexdigest()}"

    @staticmethod
    def _clamp(value: Any, default: float = 0.0) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, value)) if math.isfinite(value) else default

    def record_evidence(
        self, *, source: str, kind: str, subject: str, observed_at: float,
        payload: Mapping[str, Any], confidence: float = 1.0, provenance: str = ""
    ) -> Evidence:
        """Record an immutable observation. Existing IDs are never overwritten."""
        if not source.strip() or not kind.strip() or not subject.strip():
            raise ValueError("source, kind, and subject are required")
        evidence_payload = {
            "source": source, "kind": kind, "subject": subject,
            "observed_at": float(observed_at), "payload": dict(payload),
            "confidence": self._clamp(confidence), "provenance": provenance,
        }
        evidence_id = self._id("evidence", evidence_payload)
        evidence = Evidence(evidence_id, source, kind, subject, float(observed_at), dict(payload), self._clamp(confidence), provenance)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO control_evidence VALUES (?,?,?,?,?,?,?,?)", (
                evidence_id, source, kind, subject, evidence.observed_at,
                json.dumps(dict(payload), sort_keys=True), evidence.confidence, provenance, time.time()))
            db.commit()
        return evidence

    def evidence_for(self, subject: str, *, since: float | None = None) -> tuple[Evidence, ...]:
        query = "SELECT * FROM control_evidence WHERE subject=?"
        args: list[Any] = [subject]
        if since is not None:
            query += " AND observed_at>=?"
            args.append(float(since))
        query += " ORDER BY observed_at,evidence_id"
        with self._connect() as db:
            rows = db.execute(query, args).fetchall()
        return tuple(Evidence(r["evidence_id"], r["source"], r["kind"], r["subject"], r["observed_at"], json.loads(r["payload_json"]), r["confidence"], r["provenance"]) for r in rows)

    @staticmethod
    def _independent_sources(evidence: Sequence[Evidence]) -> tuple[str, ...]:
        return tuple(sorted({e.source for e in evidence if e.confidence > 0 and e.provenance.strip()}))

    @staticmethod
    def required_sources(*, action: str, workload_criticality: int = 1, redundancy: int = 1) -> int:
        risk = _ACTION_RISK.get(action, 3)
        criticality = max(1, min(3, int(workload_criticality)))
        redundancy = max(1, min(3, int(redundancy)))
        return min(5, max(2, risk + (criticality - 1) + (redundancy - 1)))

    def authorize(
        self, *, action: str, subject: str, evidence: Sequence[Evidence] | None = None,
        workload_criticality: int = 1, redundancy: int = 1, confidence_floor: float = 0.70,
        safety_ok: bool = True, fallback_available: bool = True, now: float | None = None
    ) -> ActionDecision:
        """Evaluate an action using independent evidence and a hard safety floor."""
        evidence = tuple(evidence if evidence is not None else self.evidence_for(subject))
        sources = self._independent_sources(evidence)
        required = self.required_sources(action=action, workload_criticality=workload_criticality, redundancy=redundancy)
        confidence = min((e.confidence for e in evidence), default=0.0)
        hard_floor = safety_ok and fallback_available
        authorized = bool(hard_floor and len(sources) >= required and confidence >= confidence_floor)
        if not safety_ok:
            reason = "hard safety floor failed"
        elif not fallback_available:
            reason = "continuous proven fallback is unavailable"
        elif len(sources) < required:
            reason = f"insufficient independent evidence: {len(sources)}/{required} sources"
        elif confidence < confidence_floor:
            reason = f"confidence below floor: {confidence:.3f}<{confidence_floor:.3f}"
        else:
            reason = "adaptive evidence threshold satisfied"
        decision_payload = {
            "action": action, "subject": subject, "risk_level": _ACTION_RISK.get(action, 3),
            "authorized": authorized, "confidence": confidence, "sources": sources,
            "required": required, "evidence_ids": [e.evidence_id for e in evidence], "reason": reason,
        }
        decision_id = self._id("decision", decision_payload)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO control_decisions VALUES (?,?,?,?,?,?,?,?,?,?)", (
                decision_id, action, _ACTION_RISK.get(action, 3), int(authorized), confidence,
                len(sources), required, json.dumps([e.evidence_id for e in evidence]), reason,
                time.time() if now is None else float(now)))
            db.commit()
        return ActionDecision(decision_id, action, _ACTION_RISK.get(action, 3), authorized, confidence, len(sources), required, tuple(e.evidence_id for e in evidence), reason)

    def register_capability(
        self, *, capability: str, incumbent_strategy_id: str | None,
        fallback_strategy_id: str | None, minimum_availability: float = 0.999,
        minimum_reliability: float = 0.999
    ) -> None:
        if not capability.strip():
            raise ValueError("capability is required")
        with self._connect() as db:
            db.execute("""INSERT INTO control_capabilities(capability,incumbent_strategy_id,fallback_strategy_id,minimum_availability,minimum_reliability,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(capability) DO UPDATE SET
                incumbent_strategy_id=excluded.incumbent_strategy_id,fallback_strategy_id=excluded.fallback_strategy_id,
                minimum_availability=excluded.minimum_availability,minimum_reliability=excluded.minimum_reliability,updated_at=excluded.updated_at""",
                (capability, incumbent_strategy_id, fallback_strategy_id, self._clamp(minimum_availability), self._clamp(minimum_reliability), time.time()))
            db.commit()

    def register_strategy(self, *, strategy_id: str, capability: str, role: str = "challenger", metadata: Mapping[str, Any] | None = None) -> StrategyDecision:
        if role not in {"champion", "challenger", "fallback"}:
            raise ValueError("unsupported strategy role")
        with self._connect() as db:
            cap = db.execute("SELECT * FROM control_capabilities WHERE capability=?", (capability,)).fetchone()
            if cap is None:
                raise ValueError("capability must be registered before strategy")
            existing = db.execute("SELECT strategy_id FROM control_strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
            if existing is not None:
                raise ValueError("strategy already exists")
            now = time.time()
            db.execute("INSERT INTO control_strategies(strategy_id,capability,role,status,version,created_at,evidence_json,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                       (strategy_id, capability, role, "active", 1, now, "{}", json.dumps(dict(metadata or {}), sort_keys=True)))
            db.commit()
        return StrategyDecision(strategy_id, capability, role, True, "registered without replacing incumbent")

    def observe_strategy(
        self, *, strategy_id: str, success: bool, performance: float | None,
        safety_ok: bool, observed_at: float, evidence: Sequence[Evidence], metadata: Mapping[str, Any] | None = None
    ) -> None:
        with self._connect() as db:
            row = db.execute("SELECT capability FROM control_strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
            if row is None:
                raise ValueError("unknown strategy")
            payload = {"strategy_id": strategy_id, "observed_at": observed_at, "success": success, "performance": performance, "evidence": [e.evidence_id for e in evidence]}
            observation_id = self._id("strategy-observation", payload)
            db.execute("INSERT OR IGNORE INTO control_strategy_observations VALUES(?,?,?,?,?,?,?,?,?)",
                       (observation_id, strategy_id, row["capability"], int(success), performance, int(safety_ok), float(observed_at), json.dumps([e.evidence_id for e in evidence]), json.dumps(dict(metadata or {}), sort_keys=True)))
            db.commit()

    def strategy_decision(self, *, strategy_id: str, window: int = 20) -> StrategyDecision:
        with self._connect() as db:
            strategy = db.execute("SELECT * FROM control_strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
            if strategy is None:
                raise ValueError("unknown strategy")
            cap = db.execute("SELECT * FROM control_capabilities WHERE capability=?", (strategy["capability"],)).fetchone()
            incumbent_id = cap["incumbent_strategy_id"] if cap else None
            rows = db.execute("SELECT * FROM control_strategy_observations WHERE strategy_id=? ORDER BY observed_at DESC LIMIT ?", (strategy_id, window)).fetchall()
            if not rows:
                return StrategyDecision(strategy_id, strategy["capability"], strategy["role"], False, "no outcome evidence")
            reliability = sum(int(r["success"]) for r in rows) / len(rows)
            safety = all(bool(r["safety_ok"]) for r in rows)
            if strategy["role"] == "champion" or strategy_id == incumbent_id:
                return StrategyDecision(strategy_id, strategy["capability"], strategy["role"], safety and reliability >= (cap["minimum_reliability"] if cap else 0.999), "incumbent remains protected")
            incumbent_rows = db.execute("SELECT * FROM control_strategy_observations WHERE strategy_id=? ORDER BY observed_at DESC LIMIT ?", (incumbent_id, window)).fetchall() if incumbent_id else []
            if not incumbent_rows:
                return StrategyDecision(strategy_id, strategy["capability"], strategy["role"], False, "incumbent has no comparable outcome window")
            challenger_perf = [r["performance"] for r in rows if r["performance"] is not None]
            incumbent_perf = [r["performance"] for r in incumbent_rows if r["performance"] is not None]
            if not challenger_perf or not incumbent_perf:
                return StrategyDecision(strategy_id, strategy["capability"], strategy["role"], False, "missing comparable performance evidence")
            challenger_mean = sum(challenger_perf) / len(challenger_perf)
            incumbent_mean = sum(incumbent_perf) / len(incumbent_perf)
            availability = sum(1 for r in rows if r["success"]) / len(rows)
            min_rel = cap["minimum_reliability"] if cap else 0.999
            min_avail = cap["minimum_availability"] if cap else 0.999
            eligible = safety and reliability >= min_rel and availability >= min_avail and challenger_mean > incumbent_mean
            reason = "sustained contextual superiority with safety and availability floors" if eligible else "challenger has not proven sustained superiority while preserving hard floors"
            return StrategyDecision(strategy_id, strategy["capability"], strategy["role"], eligible, reason)

    def promote(self, *, strategy_id: str) -> StrategyDecision:
        """Promote only a strategy that already passed the full governance gate."""
        decision = self.strategy_decision(strategy_id=strategy_id)
        if not decision.eligible:
            return decision
        now = time.time()
        with self._connect() as db:
            row = db.execute("SELECT capability FROM control_strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
            cap = db.execute("SELECT * FROM control_capabilities WHERE capability=?", (row["capability"],)).fetchone()
            incumbent = cap["incumbent_strategy_id"] if cap else None
            if not incumbent:
                return StrategyDecision(strategy_id, row["capability"], "challenger", False, "no protected incumbent")
            # The incumbent is deliberately retained as fallback during promotion.
            db.execute("UPDATE control_strategies SET role='fallback',promoted_at=COALESCE(promoted_at,?),status='active' WHERE strategy_id=?", (now, incumbent))
            db.execute("UPDATE control_strategies SET role='champion',promoted_at=?,status='active' WHERE strategy_id=?", (now, strategy_id))
            db.execute("UPDATE control_capabilities SET incumbent_strategy_id=?,fallback_strategy_id=?,updated_at=? WHERE capability=?", (strategy_id, incumbent, now, row["capability"]))
            db.commit()
        return StrategyDecision(strategy_id, row["capability"], "champion", True, "promoted while incumbent remains continuously available as fallback")

    def record_counterfactual(self, *, decision_id: str, strategy_id: str, expected_outcome: Mapping[str, Any], confidence: float, evidence: Sequence[Evidence]) -> str:
        payload = {"decision_id": decision_id, "strategy_id": strategy_id, "expected": dict(expected_outcome), "confidence": confidence, "evidence": [e.evidence_id for e in evidence]}
        identifier = self._id("counterfactual", payload)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO control_counterfactuals VALUES(?,?,?,?,?,?,?)", (identifier, decision_id, strategy_id, json.dumps(dict(expected_outcome), sort_keys=True), self._clamp(confidence), json.dumps([e.evidence_id for e in evidence]), time.time()))
            db.commit()
        return identifier

    def record_outcome(self, *, decision_id: str, outcome: str, observed_at: float, metrics: Mapping[str, Any], evidence: Sequence[Evidence], strategy_id: str | None = None) -> str:
        if outcome not in {"success", "failure", "partial", "rolled_back"}:
            raise ValueError("unsupported outcome")
        payload = {"decision_id": decision_id, "strategy_id": strategy_id, "outcome": outcome, "observed_at": observed_at, "metrics": dict(metrics), "evidence": [e.evidence_id for e in evidence]}
        identifier = self._id("outcome", payload)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO control_outcomes VALUES(?,?,?,?,?,?,?,?)", (identifier, decision_id, strategy_id, outcome, float(observed_at), json.dumps(dict(metrics), sort_keys=True), json.dumps([e.evidence_id for e in evidence]), time.time()))
            db.commit()
        return identifier

    def capability_state(self, capability: str) -> dict[str, Any] | None:
        with self._connect() as db:
            cap = db.execute("SELECT * FROM control_capabilities WHERE capability=?", (capability,)).fetchone()
            if cap is None:
                return None
            incumbent = db.execute("SELECT * FROM control_strategies WHERE strategy_id=?", (cap["incumbent_strategy_id"],)).fetchone() if cap["incumbent_strategy_id"] else None
            fallback = db.execute("SELECT * FROM control_strategies WHERE strategy_id=?", (cap["fallback_strategy_id"],)).fetchone() if cap["fallback_strategy_id"] else None
        return {
            "capability": capability,
            "incumbent_strategy_id": cap["incumbent_strategy_id"],
            "fallback_strategy_id": cap["fallback_strategy_id"],
            "incumbent_available": bool(incumbent and incumbent["status"] == "active" and float(incumbent["availability"]) >= cap["minimum_availability"]),
            "fallback_available": bool(fallback and fallback["status"] == "active" and float(fallback["availability"]) >= cap["minimum_availability"]),
            "minimum_availability": cap["minimum_availability"],
            "minimum_reliability": cap["minimum_reliability"],
        }
