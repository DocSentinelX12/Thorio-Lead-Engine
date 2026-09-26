"""Durable global coordinator for the multi-supercomputer fabric.

This layer coordinates already-authorized physical candidates. It never invents
fabric paths, worker identities, GPU health, or physical recovery truth. Those
remain owned by the lower fabric/placement/recovery authorities.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class NodeCapacity:
    node_id: str
    failure_domain: str
    gpu_slots: int
    cpu_slots: int
    memory_units: int

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.failure_domain.strip():
            raise ValueError("node_id and failure_domain are required")
        if min(self.gpu_slots, self.cpu_slots, self.memory_units) < 1:
            raise ValueError("node capacities must be positive")


@dataclass(frozen=True)
class PlacementCandidate:
    workload_id: str
    node_id: str
    failure_domain: str
    fabric_path_id: str
    score: float
    independent: bool = True

    def __post_init__(self) -> None:
        if not self.workload_id.strip() or not self.node_id.strip():
            raise ValueError("workload_id and node_id are required")
        if not self.fabric_path_id.strip():
            raise ValueError("fabric_path_id is required")


class FabricCoordinatorError(RuntimeError):
    """Raised when a durable coordination invariant prevents a safe allocation."""


class FabricCoordinator:
    """Coordinate competing workloads with durable reservations and recovery."""

    def __init__(self, db_path: str = ":memory:", *, standby_capacity: int = 1):
        if standby_capacity < 0:
            raise ValueError("standby_capacity must not be negative")
        self.db_path = db_path
        self.standby_capacity = standby_capacity
        self.physical_path_authority = None
        self._memory = sqlite3.connect(":memory:") if db_path == ":memory:" else None
        if self._memory:
            self._memory.row_factory = sqlite3.Row
        self._initialize()

    def bind_physical_path_authority(self, authority: Any) -> None:
        if authority is None or not callable(getattr(authority, "verified_physical_paths", None)):
            raise ValueError("a physical path authority with verified_physical_paths() is required")
        self.physical_path_authority = authority

    def _verified_path_ids(self) -> set[str]:
        if self.physical_path_authority is None:
            raise RuntimeError("physical path authority is not bound")
        return {
            str(row.get("path_id") or "").strip()
            for row in self.physical_path_authority.verified_physical_paths()
            if str(row.get("path_id") or "").strip()
        }

    def capacity_state(self) -> dict[str, Any]:
        with self._connect() as db:
            available_nodes = int(db.execute("SELECT COUNT(*) AS n FROM nodes WHERE state='available'").fetchone()["n"])
            active_allocations = int(db.execute("SELECT COUNT(*) AS n FROM allocations WHERE state='active'").fetchone()["n"])
            rows = db.execute("SELECT node_id FROM nodes WHERE state='available' ORDER BY node_id").fetchall()
            occupied = {str(r["node_id"]) for r in db.execute("SELECT node_id FROM allocations WHERE state='active'").fetchall()}
            protected = tuple(str(r["node_id"]) for r in rows if str(r["node_id"]) not in occupied)[: self.standby_capacity]
        free_capacity = available_nodes - active_allocations
        return {
            "available_nodes": available_nodes,
            "active_allocations": active_allocations,
            "free_capacity": free_capacity,
            "recovery_capacity_available": free_capacity > self.standby_capacity,
            "standby_capacity_available": len(protected) >= self.standby_capacity if self.standby_capacity else True,
            "protected_standby_nodes": protected,
        }

    def _connect(self) -> sqlite3.Connection:
        if self._memory:
            return self._memory
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS nodes(
                    node_id TEXT PRIMARY KEY,
                    failure_domain TEXT NOT NULL,
                    gpu_slots INTEGER NOT NULL,
                    cpu_slots INTEGER NOT NULL,
                    memory_units INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'available',
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workloads(
                    workload_id TEXT PRIMARY KEY,
                    criticality INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    generation INTEGER NOT NULL DEFAULT 1,
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS allocations(
                    workload_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    failure_domain TEXT NOT NULL,
                    fabric_path_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    generation INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions(
                    decision_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    workload_id TEXT,
                    generation INTEGER,
                    payload TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alloc_node ON allocations(node_id, state);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_allocation_node_unique
                    ON allocations(node_id) WHERE state='active';
                CREATE INDEX IF NOT EXISTS idx_workload_state ON workloads(state);
                """
            )

    @staticmethod
    def _decision_id(kind: str, payload: Mapping[str, Any]) -> str:
        material = json.dumps({"kind": kind, **payload}, sort_keys=True, separators=(",", ":"))
        return "coord:" + hashlib.sha256(material.encode()).hexdigest()

    def register_node(self, capacity: NodeCapacity) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO nodes VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(node_id) DO UPDATE SET failure_domain=excluded.failure_domain,
                   gpu_slots=excluded.gpu_slots,cpu_slots=excluded.cpu_slots,
                   memory_units=excluded.memory_units,
                   state=CASE WHEN nodes.state='failed' THEN 'failed' ELSE 'available' END,
                   updated=excluded.updated""",
                (capacity.node_id, capacity.failure_domain, capacity.gpu_slots,
                 capacity.cpu_slots, capacity.memory_units, "available", now),
            )

    def submit_workload(self, workload_id: str, *, criticality: int = 1) -> None:
        if not workload_id.strip() or criticality < 1 or criticality > 3:
            raise ValueError("workload_id and criticality 1..3 are required")
        with self._connect() as db:
            db.execute(
                """INSERT INTO workloads(workload_id,criticality,state,generation,updated)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(workload_id) DO UPDATE SET criticality=excluded.criticality,
                   state=CASE WHEN workloads.state='failed' THEN workloads.state ELSE 'queued' END,
                   updated=excluded.updated""",
                (workload_id, criticality, "queued", 1, time.time()),
            )

    def _eligible_candidates(self, candidates: Iterable[PlacementCandidate]) -> list[PlacementCandidate]:
        rows = list(candidates)
        verified_path_ids = self._verified_path_ids()
        with self._connect() as db:
            nodes = {r["node_id"]: r for r in db.execute("SELECT * FROM nodes").fetchall()}
            allocations = {r["node_id"] for r in db.execute("SELECT node_id FROM allocations WHERE state='active'").fetchall()}
        result: list[PlacementCandidate] = []
        for candidate in rows:
            node = nodes.get(candidate.node_id)
            if node is None:
                raise ValueError(f"unknown coordination node: {candidate.node_id}")
            if node["state"] != "available" or candidate.failure_domain != node["failure_domain"]:
                continue
            if candidate.node_id in allocations:
                continue
            if candidate.fabric_path_id not in verified_path_ids:
                raise ValueError(f"unverified physical fabric path: {candidate.fabric_path_id}")
            if not candidate.independent:
                continue
            result.append(candidate)
        return result

    def coordinate(self, candidates: Sequence[PlacementCandidate]) -> dict[str, Any]:
        eligible = self._eligible_candidates(candidates)
        by_workload: dict[str, list[PlacementCandidate]] = {}
        for candidate in eligible:
            by_workload.setdefault(candidate.workload_id, []).append(candidate)
        with self._connect() as db:
            workloads = {r["workload_id"]: r for r in db.execute("SELECT * FROM workloads WHERE state='queued'").fetchall()}
            ordered = sorted(by_workload, key=lambda wid: (-int(workloads.get(wid, {"criticality": 1})["criticality"]), wid))
            used_nodes: set[str] = set()
            allocations: list[dict[str, Any]] = []
            for workload_id in ordered:
                if workload_id not in workloads:
                    raise ValueError(f"unknown coordination workload: {workload_id}")
                choices = sorted(by_workload[workload_id], key=lambda x: (-x.score, x.node_id, x.fabric_path_id))
                choice = next((x for x in choices if x.node_id not in used_nodes), None)
                if choice is None:
                    continue
                generation = int(workloads[workload_id]["generation"])
                record = {
                    "workload_id": workload_id,
                    "node_id": choice.node_id,
                    "failure_domain": choice.failure_domain,
                    "fabric_path_id": choice.fabric_path_id,
                    "score": choice.score,
                    "generation": generation,
                    "state": "active",
                }
                try:
                    db.execute(
                        "INSERT INTO allocations VALUES(?,?,?,?,?,?,?,?)",
                        (workload_id, choice.node_id, choice.failure_domain, choice.fabric_path_id,
                         choice.score, generation, "active", time.time()),
                    )
                except sqlite3.IntegrityError as exc:
                    raise FabricCoordinatorError(
                        f"active allocation conflict for node {choice.node_id} or workload {workload_id}"
                    ) from exc
                db.execute("UPDATE workloads SET state='running',updated=? WHERE workload_id=?", (time.time(), workload_id))
                used_nodes.add(choice.node_id)
                allocations.append(record)
            standby = self._standby_nodes(db, used_nodes)
            payload = {"allocations": allocations, "standby_node_ids": standby}
            decision_id = self._decision_id("coordinate", payload)
            db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)", (decision_id, "coordinate", None, None, json.dumps(payload, sort_keys=True), time.time()))
            return payload

    def _standby_nodes(self, db: sqlite3.Connection, used_nodes: set[str]) -> list[str]:
        if self.standby_capacity == 0:
            return []
        rows = db.execute("SELECT node_id FROM nodes WHERE state='available' ORDER BY node_id").fetchall()
        return [r["node_id"] for r in rows if r["node_id"] not in used_nodes][: self.standby_capacity]

    def reconcile_node_failure(self, node_id: str, *, candidates: Sequence[PlacementCandidate]) -> dict[str, Any]:
        now = time.time()
        with self._connect() as db:
            node = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if node is None:
                raise ValueError(f"unknown coordination node: {node_id}")
            if node["state"] == "failed":
                prior = db.execute(
                    "SELECT payload FROM decisions WHERE kind='reconcile_failure' ORDER BY created DESC"
                ).fetchall()
                for row in prior:
                    payload = json.loads(row["payload"])
                    if payload.get("failed_node_id") == node_id:
                        return payload
            db.execute("UPDATE nodes SET state='failed',updated=? WHERE node_id=?", (now, node_id))
            affected = db.execute("SELECT * FROM allocations WHERE node_id=? AND state='active' ORDER BY workload_id", (node_id,)).fetchall()
            affected_ids = [r["workload_id"] for r in affected]
            if not affected_ids:
                payload = {"failed_node_id": node_id, "migrated": [], "unplaced_workload_ids": []}
                return payload
            available = self._eligible_candidates(candidates)
            available_by_workload: dict[str, list[PlacementCandidate]] = {}
            for c in available:
                available_by_workload.setdefault(c.workload_id, []).append(c)
            occupied = {r["node_id"] for r in db.execute("SELECT node_id FROM allocations WHERE state='active' AND node_id!=?", (node_id,)).fetchall()}
            migrated: list[dict[str, Any]] = []
            unplaced: list[str] = []
            for allocation in affected:
                choices = sorted(available_by_workload.get(allocation["workload_id"], []), key=lambda x: (-x.score, x.node_id, x.fabric_path_id))
                choice = next((x for x in choices if x.node_id not in occupied), None)
                if choice is None:
                    db.execute("UPDATE allocations SET state='unplaced',updated=? WHERE workload_id=?", (now, allocation["workload_id"]))
                    db.execute("UPDATE workloads SET state='queued',generation=generation+1,updated=? WHERE workload_id=?", (now, allocation["workload_id"]))
                    unplaced.append(allocation["workload_id"])
                    continue
                db.execute("UPDATE allocations SET node_id=?,failure_domain=?,fabric_path_id=?,score=?,generation=generation+1,updated=? WHERE workload_id=?", (choice.node_id, choice.failure_domain, choice.fabric_path_id, choice.score, now, allocation["workload_id"]))
                db.execute("UPDATE workloads SET generation=generation+1,state='running',updated=? WHERE workload_id=?", (now, allocation["workload_id"]))
                occupied.add(choice.node_id)
                migrated.append({"workload_id": allocation["workload_id"], "node_id": choice.node_id, "failure_domain": choice.failure_domain, "fabric_path_id": choice.fabric_path_id, "generation": int(allocation["generation"]) + 1})
            payload = {"failed_node_id": node_id, "migrated": migrated, "unplaced_workload_ids": unplaced}
            decision_id = self._decision_id("reconcile_failure", payload)
            db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)", (decision_id, "reconcile_failure", None, None, json.dumps(payload, sort_keys=True), now))
            return payload

    def can_experiment(self, *, required_nodes: int) -> bool:
        if required_nodes < 1:
            raise ValueError("required_nodes must be positive")
        with self._connect() as db:
            available = db.execute("SELECT COUNT(*) AS n FROM nodes WHERE state='available'").fetchone()["n"]
            active = db.execute("SELECT COUNT(*) AS n FROM allocations WHERE state='active'").fetchone()["n"]
            # Experimental work may consume only capacity strictly beyond both
            # the production allocation set and the configured standby reserve.
            # Equality is intentionally insufficient: the reserve must remain
            # available while the experiment is running.
            return available - active > self.standby_capacity + required_nodes

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as db:
            nodes = [dict(r) for r in db.execute("SELECT * FROM nodes ORDER BY node_id")]
            workloads = [dict(r) for r in db.execute("SELECT * FROM workloads ORDER BY workload_id")]
            allocations = [dict(r) for r in db.execute("SELECT * FROM allocations WHERE state IN ('active','unplaced') ORDER BY CASE state WHEN 'active' THEN 0 ELSE 1 END, workload_id")]
            decisions = [dict(r) for r in db.execute("SELECT * FROM decisions ORDER BY created DESC LIMIT 100")]
        return {"nodes": nodes, "workloads": workloads, "allocations": allocations, "decisions": decisions}
