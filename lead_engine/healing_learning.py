"""Isolated recovery-strategy learning and promotion governance."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


class HealingLearning:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._memory = sqlite3.connect(":memory:") if db_path == ":memory:" else None
        if self._memory:
            self._memory.row_factory = sqlite3.Row
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS healing_learning(
                strategy TEXT PRIMARY KEY,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'EXPERIMENTAL',
                provenance_json TEXT NOT NULL DEFAULT '[]',
                updated_at REAL NOT NULL
            )""")

    def _connect(self) -> sqlite3.Connection:
        if self._memory:
            return self._memory
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def record(self, strategy: str, *, success: bool, evidence: dict[str, Any]) -> dict[str, Any]:
        if not strategy.strip():
            raise ValueError("strategy is required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM healing_learning WHERE strategy=?", (strategy,)).fetchone()
            provenance = json.loads(row["provenance_json"]) if row else []
            provenance.append({"success": success, "evidence": evidence, "recorded_at": time.time()})
            successes = int(row["successes"]) if row else 0
            failures = int(row["failures"]) if row else 0
            successes += int(success)
            failures += int(not success)
            db.execute(
                """INSERT INTO healing_learning(strategy,successes,failures,state,provenance_json,updated_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(strategy) DO UPDATE SET successes=excluded.successes,failures=excluded.failures,
                   provenance_json=excluded.provenance_json,updated_at=excluded.updated_at""",
                (strategy, successes, failures, row["state"] if row else "EXPERIMENTAL",
                 json.dumps(provenance, sort_keys=True), time.time()),
            )
            return self.status(strategy)

    def status(self, strategy: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM healing_learning WHERE strategy=?", (strategy,)).fetchone()
            if not row:
                return {"strategy": strategy, "state": "UNKNOWN", "successes": 0, "failures": 0}
            return dict(row)

    def promote(self, strategy: str, *, known_good_available: bool) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM healing_learning WHERE strategy=?", (strategy,)).fetchone()
            if not row:
                raise ValueError("unknown strategy")
            if not known_good_available or int(row["successes"]) < 3 or int(row["failures"]) != 0:
                raise ValueError("promotion evidence or known-good continuity requirement not satisfied")
            db.execute("UPDATE healing_learning SET state='PROMOTED',updated_at=? WHERE strategy=?", (time.time(), strategy))
            return self.status(strategy)

    def demote_on_regression(self, strategy: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM healing_learning WHERE strategy=?", (strategy,)).fetchone()
            if not row:
                raise ValueError("unknown strategy")
            if int(row["failures"]) < 2:
                raise ValueError("regression evidence is insufficient")
            db.execute("UPDATE healing_learning SET state='DEMOTED',updated_at=? WHERE strategy=?", (time.time(), strategy))
            return self.status(strategy)
