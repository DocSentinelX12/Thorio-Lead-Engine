"""Dependency-aware autonomous healing planning and reconciliation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .healing_dependencies import HealingDependencyAnalyzer
from .healing_evidence import HealingEvidenceGraph


class HealingIntelligence:
    """Plans recovery above authoritative executors and reconciles durable intent."""

    _RECOVERY_STEPS = (
        ("physical_reverify", "compute_inventory"),
        ("active_measurement", "compute_inventory"),
        ("route_reconcile", "recovery_orchestrator"),
        ("workload_reconcile", "workload_recovery"),
        ("closure", "healing_closure"),
    )

    def __init__(
        self,
        *,
        graph: HealingEvidenceGraph,
        dependencies: HealingDependencyAnalyzer,
        db_path: str = ":memory:",
    ):
        self.graph = graph
        self.dependencies = dependencies
        self.db_path = db_path
        self._memory = sqlite3.connect(":memory:") if db_path == ":memory:" else None
        if self._memory:
            self._memory.row_factory = sqlite3.Row
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._memory:
            return self._memory
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS healing_intelligence_plans(
                    plan_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_healing_intelligence_scope "
                "ON healing_intelligence_plans(scope_id,generation,state)"
            )

    @staticmethod
    def _id(scope_id: str, generation: int, strategy: str) -> str:
        material = f"{scope_id}\0{generation}\0{strategy}"
        return "healplan:" + hashlib.sha256(material.encode()).hexdigest()

    def plan(
        self,
        *,
        scope_id: str,
        generation: int,
        strategy: str,
        criticality: int,
        confidence: float,
        reversible: bool,
        cascade_risk: float,
        redundant_capacity: bool,
        standby_capacity_available: bool,
        fabric_path_id: str,
    ) -> dict[str, Any]:
        if not scope_id.strip() or not strategy.strip() or not fabric_path_id.strip():
            raise ValueError("scope_id, strategy, and fabric_path_id are required")
        if generation < 1 or criticality not in (1, 2, 3):
            raise ValueError("generation and criticality are invalid")
        if not 0.0 <= confidence <= 1.0 or not 0.0 <= cascade_risk <= 1.0:
            raise ValueError("confidence and cascade_risk must be between 0 and 1")

        evidence = self.graph.snapshot(scope_id)
        if fabric_path_id not in evidence["path_ids"]:
            raise ValueError("exact fabric path identity is absent from authoritative evidence")
        impact = self.dependencies.impact(scope_id)
        serialized = not redundant_capacity or not standby_capacity_available
        degraded = not redundant_capacity and not standby_capacity_available

        plan_id = self._id(scope_id, generation, strategy)
        steps = []
        previous: str | None = None
        for kind, authority in self._RECOVERY_STEPS:
            step_material = f"{plan_id}\0{kind}"
            step_id = "step:" + hashlib.sha256(step_material.encode()).hexdigest()
            step = {
                "step_id": step_id,
                "kind": kind,
                "authority": authority,
                "fabric_path_id": fabric_path_id,
                "depends_on": (previous,) if previous else (),
                "state": "PLANNED",
            }
            steps.append(step)
            previous = step_id

        if confidence < 0.75 or cascade_risk >= 0.75:
            mode = "SERIALIZED"
        elif serialized:
            mode = "SERIALIZED"
        else:
            mode = "PARALLEL_INDEPENDENT"

        payload = {
            "scope_id": scope_id,
            "generation": generation,
            "strategy": strategy,
            "criticality": criticality,
            "confidence": confidence,
            "reversible": reversible,
            "cascade_risk": cascade_risk,
            "redundant_capacity": redundant_capacity,
            "standby_capacity_available": standby_capacity_available,
            "mode": mode,
            "requires_degraded_mode": degraded,
            "affected_entities": impact["affected_entities"],
            "failure_domains": impact["failure_domains"],
            "steps": steps,
        }
        import time
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO healing_intelligence_plans
                   (plan_id,scope_id,generation,strategy,state,payload_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(plan_id) DO UPDATE SET payload_json=excluded.payload_json,
                   updated_at=excluded.updated_at""",
                (plan_id, scope_id, generation, strategy, "PLANNED",
                 json.dumps(payload, sort_keys=True, default=str), now, now),
            )
            row = db.execute(
                "SELECT * FROM healing_intelligence_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["plan_id"] = plan_id
        result.update(result.pop("payload"))
        result["plan_id"] = plan_id
        result["affected_entities"] = tuple(tuple(item) for item in result["affected_entities"])
        result["failure_domains"] = tuple(result["failure_domains"])
        result["steps"] = tuple(
            {**step, "depends_on": tuple(step["depends_on"])}
            for step in result["steps"]
        )
        return result

    def reconcile(
        self,
        *,
        plan_id: str,
        authoritative_state: dict[str, Any],
        observed_steps: tuple[str, ...] | list[str],
    ) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM healing_intelligence_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if not row:
                raise ValueError("unknown healing plan")
            payload = json.loads(row["payload_json"])

        path_id = str(authoritative_state.get("path_id") or "").strip()
        if path_id != payload["steps"][0]["fabric_path_id"]:
            decision = "REPLAN"
        elif authoritative_state.get("state") in {"MEASURED", "REVERIFIED"} and authoritative_state.get("allow_routing") is True:
            expected = [step["kind"] for step in payload["steps"]]
            observed = tuple(observed_steps)
            decision = "RESUME" if all(item in expected for item in observed) else "REPLAN"
        elif authoritative_state.get("state") in {"FAILED", "DEGRADED"}:
            decision = "REPLAN"
        else:
            decision = "COMPENSATE" if payload["reversible"] else "REPLAN"

        import time
        with self._connect() as db:
            db.execute(
                "UPDATE healing_intelligence_plans SET state=?,updated_at=? WHERE plan_id=?",
                (decision, time.time(), plan_id),
            )
        return {
            "plan_id": plan_id,
            "decision": decision,
            "authoritative_state": dict(authoritative_state),
            "observed_steps": tuple(observed_steps),
        }
