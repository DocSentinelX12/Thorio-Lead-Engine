"""Durable state authority for autonomous healing lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Mapping


class HealingStateError(RuntimeError):
    pass


class HealingState:
    """Own healing lifecycle state without becoming a physical-state authority."""

    def __init__(self, db_path: str = ":memory__"):
        self.db_path = ":memory:" if db_path in {":memory:", ":memory__"} else db_path
        self._memory = sqlite3.connect(":memory:") if self.db_path == ":memory:" else None
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
            db.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS healing_actions(
                    action_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    failure_fingerprint TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'PLANNED',
                    owner TEXT,
                    lease_expires_at REAL,
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    checkpoint TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_healing_action_generation
                    ON healing_actions(scope_id,generation,failure_fingerprint);
                CREATE TABLE IF NOT EXISTS healing_events(
                    event_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES healing_actions(action_id)
                );
                CREATE TABLE IF NOT EXISTS healing_checkpoints(
                    checkpoint_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES healing_actions(action_id)
                );
                CREATE TABLE IF NOT EXISTS healing_reconciliations(
                    reconciliation_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    authoritative_state_json TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES healing_actions(action_id)
                );
                CREATE TABLE IF NOT EXISTS healing_degraded(
                    scope_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    entered_at REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_healing_actions_due
                    ON healing_actions(state,lease_expires_at,updated_at);
            """)

    @staticmethod
    def _id(scope_id: str, fingerprint: str, generation: int) -> str:
        material = f"{scope_id}\0{fingerprint}\0{generation}"
        return "heal:" + hashlib.sha256(material.encode()).hexdigest()

    def ensure_action(self, *, scope_id: str, failure_fingerprint: str,
                      generation: int, strategy: str) -> dict[str, Any]:
        if not scope_id.strip() or not failure_fingerprint.strip() or generation < 1 or not strategy.strip():
            raise ValueError("scope_id, failure_fingerprint, generation, and strategy are required")
        now = time.time()
        action_id = self._id(scope_id, failure_fingerprint, generation)
        with self._connect() as db:
            existing = db.execute("SELECT * FROM healing_actions WHERE action_id=?", (action_id,)).fetchone()
            if existing:
                return self._row(db, existing["action_id"])
            db.execute(
                """INSERT INTO healing_actions(action_id,scope_id,failure_fingerprint,generation,strategy,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (action_id, scope_id, failure_fingerprint, generation, strategy, now, now),
            )
            self._event(db, action_id, "created", {"strategy": strategy, "generation": generation}, now)
            return self._row(db, action_id)

    def _row(self, db: sqlite3.Connection, action_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM healing_actions WHERE action_id=?", (action_id,)).fetchone()
        if not row:
            raise HealingStateError("unknown healing action")
        data = dict(row)
        recon = db.execute(
            "SELECT authoritative_state_json,observed_at FROM healing_reconciliations WHERE action_id=? ORDER BY observed_at DESC LIMIT 1",
            (action_id,),
        ).fetchone()
        data["reconciliation"] = (
            {"authoritative_state": json.loads(recon["authoritative_state_json"]), "observed_at": recon["observed_at"]}
            if recon else None
        )
        return data

    def _event(self, db: sqlite3.Connection, action_id: str, kind: str, payload: Mapping[str, Any], now: float) -> None:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        event_id = "event:" + hashlib.sha256(f"{action_id}\0{kind}\0{now}\0{raw}".encode()).hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO healing_events(event_id,action_id,kind,payload_json,created_at) VALUES(?,?,?,?,?)",
            (event_id, action_id, kind, raw, now),
        )

    def _check_owner(self, db: sqlite3.Connection, action_id: str, owner: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM healing_actions WHERE action_id=?", (action_id,)).fetchone()
        if not row:
            raise HealingStateError("unknown healing action")
        if row["owner"] != owner:
            raise HealingStateError("fenced owner")
        return row

    def claim_action(self, action_id: str, *, owner: str, now: float | None = None,
                     lease_seconds: float = 300.0) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        if not owner.strip() or lease_seconds <= 0:
            raise ValueError("owner and positive lease_seconds are required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM healing_actions WHERE action_id=?", (action_id,)).fetchone()
            if not row:
                raise HealingStateError("unknown healing action")
            newest = db.execute(
                "SELECT MAX(generation) AS generation FROM healing_actions WHERE scope_id=?",
                (row["scope_id"],),
            ).fetchone()["generation"]
            if int(row["generation"]) < int(newest):
                raise HealingStateError("stale generation")
            if row["owner"] and row["lease_expires_at"] is not None and float(row["lease_expires_at"]) > now and row["owner"] != owner:
                raise HealingStateError("action lease is active")
            token = int(row["fencing_token"]) + 1
            db.execute(
                """UPDATE healing_actions SET owner=?,lease_expires_at=?,fencing_token=?,state='CLAIMED',updated_at=?
                   WHERE action_id=?""",
                (owner, now + lease_seconds, token, now, action_id),
            )
            self._event(db, action_id, "claimed", {"owner": owner, "fencing_token": token}, now)
            return self._row(db, action_id)

    def checkpoint(self, *, action_id: str, owner: str, checkpoint: str,
                   payload: Mapping[str, Any]) -> dict[str, Any]:
        now = time.time()
        if not checkpoint.strip():
            raise ValueError("checkpoint is required")
        with self._connect() as db:
            row = self._check_owner(db, action_id, owner)
            if row["lease_expires_at"] is None or float(row["lease_expires_at"]) <= now:
                raise HealingStateError("fenced owner")
            checkpoint_id = "checkpoint:" + hashlib.sha256(
                f"{action_id}\0{row['fencing_token']}\0{checkpoint}\0{now}".encode()
            ).hexdigest()
            raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
            db.execute(
                "INSERT INTO healing_checkpoints VALUES(?,?,?,?,?,?)",
                (checkpoint_id, action_id, checkpoint, raw, row["fencing_token"], now),
            )
            db.execute(
                "UPDATE healing_actions SET checkpoint=?,state='IN_PROGRESS',updated_at=? WHERE action_id=?",
                (checkpoint, now, action_id),
            )
            self._event(db, action_id, "checkpoint", {"name": checkpoint, "payload": dict(payload)}, now)
            return self._row(db, action_id)

    def record_reconciliation(self, *, action_id: str, authoritative_state: Mapping[str, Any],
                              observed_at: float) -> dict[str, Any]:
        now = time.time()
        raw = json.dumps(dict(authoritative_state), sort_keys=True, separators=(",", ":"), default=str)
        reconciliation_id = "reconcile:" + hashlib.sha256(
            f"{action_id}\0{observed_at}\0{raw}".encode()
        ).hexdigest()
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO healing_reconciliations VALUES(?,?,?,?,?)",
                (reconciliation_id, action_id, raw, float(observed_at), now),
            )
            self._event(db, action_id, "reconciled", {"authoritative_state": dict(authoritative_state)}, now)
            return self._row(db, action_id)

    def enter_degraded(self, *, scope_id: str, reason: str, now: float | None = None) -> None:
        now = time.time() if now is None else float(now)
        if not scope_id.strip() or not reason.strip():
            raise ValueError("scope_id and reason are required")
        with self._connect() as db:
            db.execute(
                "INSERT INTO healing_degraded(scope_id,reason,entered_at,active) VALUES(?,?,?,1) "
                "ON CONFLICT(scope_id) DO UPDATE SET reason=excluded.reason,entered_at=excluded.entered_at,active=1",
                (scope_id, reason, now),
            )

    def degraded_scope(self, scope_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM healing_degraded WHERE scope_id=?", (scope_id,)).fetchone()
            return dict(row) if row else None

    def action(self, action_id: str) -> dict[str, Any]:
        with self._connect() as db:
            return self._row(db, action_id)

    def list_actions(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT action_id FROM healing_actions ORDER BY created_at,action_id").fetchall()
            return [self._row(db, row["action_id"]) for row in rows]
