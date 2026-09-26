"""Crash-safe control-plane recovery and fencing."""

from __future__ import annotations

import sqlite3
from typing import Any


class ControlPlaneRecoveryError(RuntimeError):
    pass


class ControlPlaneRecovery:
    def __init__(self, db_path: str = ":memory:"):
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
            db.executescript("""
                CREATE TABLE IF NOT EXISTS control_plane_recovery(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    controller_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    reconciled INTEGER NOT NULL DEFAULT 0,
                    authoritative_state_json TEXT
                );
            """)
            row = db.execute("SELECT singleton FROM control_plane_recovery WHERE singleton=1").fetchone()
            if not row:
                db.execute(
                    "INSERT INTO control_plane_recovery(singleton,controller_id,generation,fencing_token,state) VALUES(1,'',0,0,'EMPTY')"
                )

    def register(self, controller_id: str, *, generation: int) -> dict[str, Any]:
        if not controller_id.strip() or generation < 1:
            raise ValueError("controller_id and positive generation are required")
        with self._connect() as db:
            db.execute(
                "UPDATE control_plane_recovery SET controller_id=?,generation=?,fencing_token=?,state='ACTIVE',reconciled=1 WHERE singleton=1",
                (controller_id, generation, generation),
            )
            result = dict(db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone())
        return result

    def mark_partition(self) -> None:
        with self._connect() as db:
            db.execute("UPDATE control_plane_recovery SET state='PARTITIONED',reconciled=0 WHERE singleton=1")

    def takeover(self, controller_id: str, *, generation: int) -> dict[str, Any]:
        if not controller_id.strip() or generation < 1:
            raise ValueError("controller_id and positive generation are required")
        with self._connect() as db:
            current = db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone()
            if current["state"] == "PARTITIONED":
                raise ControlPlaneRecoveryError("partition prevents safe takeover")
            if generation <= int(current["generation"]):
                raise ControlPlaneRecoveryError("generation is not newer than current authority")
            token = int(current["fencing_token"]) + 1
            db.execute(
                """UPDATE control_plane_recovery
                   SET controller_id=?,generation=?,fencing_token=?,state='FENCED_PENDING_RECONCILIATION',reconciled=0
                   WHERE singleton=1""",
                (controller_id, generation, token),
            )
            result = dict(db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone())
        return result

    def is_fenced(self, controller_id: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT controller_id,state FROM control_plane_recovery WHERE singleton=1").fetchone()
            return row["controller_id"] != controller_id or row["state"] != "ACTIVE"

    def reconcile(self, controller_id: str, *, generation: int,
                   authoritative_state: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone()
            if row["controller_id"] != controller_id or int(row["generation"]) != generation:
                raise ControlPlaneRecoveryError("controller is fenced")
            import json
            db.execute(
                "UPDATE control_plane_recovery SET reconciled=1,authoritative_state_json=? WHERE singleton=1",
                (json.dumps(authoritative_state, sort_keys=True),),
            )
            result = dict(db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone())
        return result

    def activate(self, controller_id: str, *, generation: int) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone()
            if row["controller_id"] != controller_id or int(row["generation"]) != generation:
                raise ControlPlaneRecoveryError("controller is fenced")
            if row["state"] == "PARTITIONED":
                raise ControlPlaneRecoveryError("partition prevents activation")
            if not row["reconciled"]:
                raise ControlPlaneRecoveryError("reconciliation is required before activation")
            db.execute("UPDATE control_plane_recovery SET state='ACTIVE' WHERE singleton=1")
            result = dict(db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone())
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as db:
            return dict(db.execute("SELECT * FROM control_plane_recovery WHERE singleton=1").fetchone())
