"""Durable champion/challenger experimentation for autonomous healing.

The experiment engine is advisory governance only. It never replaces the
authoritative physical, placement, or recovery authorities. A champion remains
available while challengers are evaluated, and every outcome is durable and
context-bound.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from typing import Any, Mapping


class HealingExperimentError(RuntimeError):
    pass


class HealingExperimentManager:
    """Crash-safe strategy experimentation with champion continuity."""

    MIN_SAMPLES = 5
    MIN_SUCCESS_RATE = 0.80
    MIN_LOWER_BOUND = 0.65
    MIN_MARGIN = 0.05

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._memory = sqlite3.connect(":memory:") if db_path == ":memory__" else None
        if self._memory:
            self._memory.row_factory = sqlite3.Row
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS healing_strategies(
              context_key TEXT NOT NULL,
              strategy TEXT NOT NULL,
              role TEXT NOT NULL,
              state TEXT NOT NULL,
              parent_strategy TEXT,
              generation INTEGER NOT NULL DEFAULT 1,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              PRIMARY KEY(context_key,strategy)
            );
            CREATE TABLE IF NOT EXISTS healing_experiments(
              experiment_id TEXT PRIMARY KEY,
              context_key TEXT NOT NULL,
              champion_strategy TEXT NOT NULL,
              challenger_strategy TEXT NOT NULL,
              state TEXT NOT NULL,
              started_at REAL NOT NULL,
              completed_at REAL,
              provenance_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS healing_experiment_outcomes(
              outcome_id TEXT PRIMARY KEY,
              experiment_id TEXT NOT NULL,
              context_key TEXT NOT NULL,
              strategy TEXT NOT NULL,
              success INTEGER NOT NULL,
              safety_violation INTEGER NOT NULL,
              reversible INTEGER NOT NULL,
              evidence_json TEXT NOT NULL,
              observed_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_healing_outcomes_context_strategy
              ON healing_experiment_outcomes(context_key,strategy,observed_at);
            CREATE TABLE IF NOT EXISTS healing_strategy_events(
              event_id TEXT PRIMARY KEY,
              context_key TEXT NOT NULL,
              strategy TEXT NOT NULL,
              event TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            """)

    def _connect(self):
        if self._memory:
            return self._memory
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def context_key(*, fabric_path_id: str, failure_domain: str = "",
                    workload_class: str = "") -> str:
        path = str(fabric_path_id).strip()
        if not path:
            raise ValueError("fabric_path_id is required")
        material = "\0".join((path, str(failure_domain).strip(), str(workload_class).strip()))
        return "context:" + hashlib.sha256(material.encode()).hexdigest()

    @staticmethod
    def _event_id(context_key: str, strategy: str, event: str, payload: Mapping[str, Any]) -> str:
        raw = json.dumps(dict(payload), sort_keys=True, default=str)
        return "experiment-event:" + hashlib.sha256(
            f"{context_key}\0{strategy}\0{event}\0{raw}".encode()
        ).hexdigest()

    @staticmethod
    def _wilson_lower(successes: int, samples: int, z: float = 1.96) -> float:
        if samples <= 0:
            return 0.0
        p = successes / samples
        denom = 1.0 + z*z/samples
        centre = p + z*z/(2*samples)
        margin = z * math.sqrt((p*(1-p) + z*z/(4*samples))/samples)
        return (centre - margin) / denom

    def _strategy(self, db, context_key: str, strategy: str):
        row = db.execute(
            "SELECT * FROM healing_strategies WHERE context_key=? AND strategy=?",
            (context_key, strategy),
        ).fetchone()
        return dict(row) if row else None

    def register_champion(self, *, context_key: str, strategy: str,
                          provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not context_key.strip() or not strategy.strip():
            raise ValueError("context_key and strategy are required")
        now = time.time()
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM healing_strategies WHERE context_key=? AND role='CHAMPION' AND state='ACTIVE'",
                (context_key,),
            ).fetchall()
            current = self._strategy(db, context_key, strategy)
            if current and current["role"] == "CHAMPION" and current["state"] == "ACTIVE":
                return current
            if existing and not current:
                raise HealingExperimentError("active champion already exists; challenger must be evaluated")
            if current and current["role"] == "CHALLENGER":
                raise HealingExperimentError("challenger cannot be promoted by registration")
            db.execute(
                """INSERT INTO healing_strategies(context_key,strategy,role,state,parent_strategy,generation,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (context_key, strategy, "CHAMPION", "ACTIVE", None, 1, now, now),
            )
            payload = {"provenance": dict(provenance or {}), "role": "CHAMPION"}
            db.execute(
                "INSERT OR IGNORE INTO healing_strategy_events VALUES(?,?,?,?,?,?)",
                (self._event_id(context_key, strategy, "registered", payload),
                 context_key, strategy, "registered", json.dumps(payload, sort_keys=True, default=str), now),
            )
            return dict(db.execute(
                "SELECT * FROM healing_strategies WHERE context_key=? AND strategy=?",
                (context_key, strategy),
            ).fetchone())

    def start_challenger(self, *, context_key: str, challenger_strategy: str,
                         provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not challenger_strategy.strip():
            raise ValueError("challenger_strategy is required")
        now = time.time()
        with self._connect() as db:
            champion = db.execute(
                "SELECT * FROM healing_strategies WHERE context_key=? AND role='CHAMPION' AND state='ACTIVE'",
                (context_key,),
            ).fetchone()
            if not champion:
                raise HealingExperimentError("active champion is required")
            if champion["strategy"] == challenger_strategy:
                raise HealingExperimentError("challenger must differ from champion")
            current = self._strategy(db, context_key, challenger_strategy)
            if current and current["state"] == "ACTIVE":
                return dict(db.execute(
                    "SELECT * FROM healing_experiments WHERE experiment_id=(SELECT experiment_id FROM healing_experiments WHERE context_key=? AND challenger_strategy=? AND state='RUNNING' ORDER BY started_at DESC LIMIT 1)",
                    (context_key, challenger_strategy),
                ).fetchone() or {"experiment_id": None, "state": "RUNNING",
                                  "challenger_strategy": challenger_strategy})
            db.execute(
                """INSERT OR REPLACE INTO healing_strategies
                   (context_key,strategy,role,state,parent_strategy,generation,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (context_key, challenger_strategy, "CHALLENGER", "ACTIVE",
                 champion["strategy"], int(champion["generation"]) + 1, now, now),
            )
            experiment_id = "experiment:" + hashlib.sha256(
                f"{context_key}\0{champion['strategy']}\0{challenger_strategy}\0{now}".encode()
            ).hexdigest()
            payload = {
                "context_key": context_key,
                "champion_strategy": champion["strategy"],
                "challenger_strategy": challenger_strategy,
                "provenance": dict(provenance or {}),
            }
            db.execute(
                "INSERT INTO healing_experiments VALUES(?,?,?,?,?,?,?,?)",
                (experiment_id, context_key, champion["strategy"], challenger_strategy,
                 "RUNNING", now, None, json.dumps(payload, sort_keys=True, default=str)),
            )
            return dict(db.execute(
                "SELECT * FROM healing_experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone())

    def record_outcome(self, *, experiment_id: str, strategy: str, success: bool,
                       safety_violation: bool = False, reversible: bool = True,
                       evidence: Mapping[str, Any] | None = None,
                       observed_at: float | None = None) -> dict[str, Any]:
        observed_at = time.time() if observed_at is None else float(observed_at)
        with self._connect() as db:
            exp = db.execute(
                "SELECT * FROM healing_experiments WHERE experiment_id=?", (experiment_id,)
            ).fetchone()
            if not exp or exp["state"] != "RUNNING":
                raise HealingExperimentError("experiment is not running")
            if strategy not in {exp["champion_strategy"], exp["challenger_strategy"]}:
                raise HealingExperimentError("strategy is outside the experiment")
            payload = dict(evidence or {})
            payload.update({
                "experiment_id": experiment_id,
                "context_key": exp["context_key"],
                "strategy": strategy,
                "safety_violation": bool(safety_violation),
                "reversible": bool(reversible),
            })
            outcome_id = "outcome:" + hashlib.sha256(
                f"{experiment_id}\0{strategy}\0{observed_at}\0{json.dumps(payload,sort_keys=True,default=str)}".encode()
            ).hexdigest()
            db.execute(
                """INSERT OR IGNORE INTO healing_experiment_outcomes
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (outcome_id, experiment_id, exp["context_key"], strategy,
                 int(bool(success)), int(bool(safety_violation)), int(bool(reversible)),
                 json.dumps(payload, sort_keys=True, default=str), observed_at),
            )
            return dict(db.execute(
                "SELECT * FROM healing_experiment_outcomes WHERE outcome_id=?", (outcome_id,)
            ).fetchone())

    def _stats(self, db, experiment_id: str, strategy: str) -> dict[str, Any]:
        rows = db.execute(
            """SELECT success,safety_violation,reversible FROM healing_experiment_outcomes
               WHERE experiment_id=? AND strategy=? ORDER BY observed_at,outcome_id""",
            (experiment_id, strategy),
        ).fetchall()
        samples = len(rows)
        successes = sum(int(r["success"]) for r in rows)
        failures = samples - successes
        violations = sum(int(r["safety_violation"]) for r in rows)
        irreversible = sum(1 for r in rows if not r["reversible"])
        rate = successes / samples if samples else 0.0
        return {
            "samples": samples, "successes": successes, "failures": failures,
            "safety_violations": violations, "irreversible_outcomes": irreversible,
            "success_rate": round(rate, 6),
            "wilson_lower": round(self._wilson_lower(successes, samples), 6),
        }

    def evaluate(self, *, experiment_id: str) -> dict[str, Any]:
        with self._connect() as db:
            exp = db.execute("SELECT * FROM healing_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            if not exp:
                raise HealingExperimentError("unknown experiment")
            champion = self._stats(db, experiment_id, exp["champion_strategy"])
            challenger = self._stats(db, experiment_id, exp["challenger_strategy"])
            eligible = (
                challenger["samples"] >= self.MIN_SAMPLES
                and challenger["safety_violations"] == 0
                and challenger["irreversible_outcomes"] == 0
                and challenger["success_rate"] >= self.MIN_SUCCESS_RATE
                and challenger["wilson_lower"] >= self.MIN_LOWER_BOUND
                and challenger["success_rate"] >= champion["success_rate"] + self.MIN_MARGIN
            )
            result = {
                "experiment_id": experiment_id,
                "context_key": exp["context_key"],
                "champion": {"strategy": exp["champion_strategy"], **champion},
                "challenger": {"strategy": exp["challenger_strategy"], **challenger},
                "promotion_eligible": bool(eligible),
                "state": str(exp["state"]),
            }
            return result

    def promote(self, *, experiment_id: str) -> dict[str, Any]:
        now = time.time()
        with self._connect() as db:
            evaluation = self.evaluate(experiment_id=experiment_id)
            if not evaluation["promotion_eligible"]:
                raise HealingExperimentError("challenger has not satisfied promotion gates")
            exp = db.execute("SELECT * FROM healing_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            db.execute(
                "UPDATE healing_strategies SET role='RETIRED',state='RETIRED',updated_at=? WHERE context_key=? AND strategy=?",
                (now, exp["context_key"], exp["champion_strategy"]),
            )
            db.execute(
                "UPDATE healing_strategies SET role='CHAMPION',state='ACTIVE',updated_at=? WHERE context_key=? AND strategy=?",
                (now, exp["context_key"], exp["challenger_strategy"]),
            )
            db.execute(
                "UPDATE healing_experiments SET state='PROMOTED',completed_at=? WHERE experiment_id=?",
                (now, experiment_id),
            )
            payload = {"evaluation": evaluation, "event": "promoted"}
            db.execute(
                "INSERT OR IGNORE INTO healing_strategy_events VALUES(?,?,?,?,?,?)",
                (self._event_id(exp["context_key"], exp["challenger_strategy"], "promoted", payload),
                 exp["context_key"], exp["challenger_strategy"], "promoted",
                 json.dumps(payload, sort_keys=True, default=str), now),
            )
            return self.status(context_key=exp["context_key"])

    def rollback(self, *, experiment_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("rollback reason is required")
        now = time.time()
        with self._connect() as db:
            exp = db.execute("SELECT * FROM healing_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            if not exp:
                raise HealingExperimentError("unknown experiment")
            # Rollback closes every active challenger in this context. The
            # previously authoritative champion is the only strategy allowed to
            # remain active after a failed experiment.
            db.execute(
                """UPDATE healing_strategies
                   SET state='RETIRED', role='RETIRED', updated_at=?
                   WHERE context_key=? AND role='CHALLENGER' AND state='ACTIVE'""",
                (now, exp["context_key"]),
            )
            db.execute(
                "UPDATE healing_strategies SET state='ACTIVE',role='CHAMPION',updated_at=? WHERE context_key=? AND strategy=?",
                (now, exp["context_key"], exp["champion_strategy"]),
            )
            db.execute(
                "UPDATE healing_experiments SET state='ROLLED_BACK',completed_at=? WHERE experiment_id=?",
                (now, experiment_id),
            )
            payload = {"reason": reason, "event": "rollback"}
            db.execute(
                "INSERT OR IGNORE INTO healing_strategy_events VALUES(?,?,?,?,?,?)",
                (self._event_id(exp["context_key"], exp["challenger_strategy"], "rollback", payload),
                 exp["context_key"], exp["challenger_strategy"], "rollback",
                 json.dumps(payload, sort_keys=True), now),
            )
            return self.status(context_key=exp["context_key"])

    def status(self, *, context_key: str) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM healing_strategies WHERE context_key=? ORDER BY generation,strategy",
                (context_key,),
            ).fetchall()
            champion = next((dict(r) for r in rows if r["role"] == "CHAMPION" and r["state"] == "ACTIVE"), None)
            challengers = tuple(dict(r) for r in rows if r["role"] == "CHALLENGER" and r["state"] == "ACTIVE")
            return {
                "context_key": context_key,
                "champion": champion,
                "challengers": challengers,
                "strategies": tuple(dict(r) for r in rows),
            }

    def select(self, *, context_key: str, known_good_strategy: str | None = None) -> dict[str, Any]:
        state = self.status(context_key=context_key)
        champion = state["champion"]
        if champion is None:
            if known_good_strategy is None:
                raise HealingExperimentError("no champion strategy is available")
            champion = self.register_champion(context_key=context_key, strategy=known_good_strategy)
        return {
            "strategy": champion["strategy"],
            "role": "CHAMPION",
            "context_key": context_key,
            "challenger_isolated": bool(state["challengers"]),
            "authoritative_execution": True,
        }
