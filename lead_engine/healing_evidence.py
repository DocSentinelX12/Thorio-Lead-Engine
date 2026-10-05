"""Durable evidence graph for autonomous healing intelligence.

The graph records evidence and derived relationships, but never becomes the
authority for physical, execution, capacity, or recovery truth.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


class HealingEvidenceGraphError(RuntimeError):
    pass


class HealingEvidenceGraph:
    """Immutable evidence and relationship store backed by SQLite."""

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
            db.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS healing_evidence_observations(
                    observation_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    observed_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_healing_evidence_observation
                    ON healing_evidence_observations(
                        scope_id, entity_type, entity_id, source_authority,
                        generation, observed_at
                    );
                CREATE TABLE IF NOT EXISTS healing_evidence_relationships(
                    relationship_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    observed_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_healing_evidence_relationship
                    ON healing_evidence_relationships(
                        scope_id, source_type, source_id, relation,
                        target_type, target_id, source_authority, generation
                    );
                CREATE INDEX IF NOT EXISTS idx_healing_evidence_obs_scope
                    ON healing_evidence_observations(scope_id, observed_at);
                CREATE INDEX IF NOT EXISTS idx_healing_evidence_rel_scope
                    ON healing_evidence_relationships(scope_id, observed_at);
                """
            )

    @staticmethod
    def _identity(prefix: str, values: tuple[object, ...]) -> str:
        material = "\0".join(str(value) for value in values)
        return f"{prefix}:" + hashlib.sha256(material.encode()).hexdigest()

    @staticmethod
    def _validate(
        *,
        scope_id: str,
        source_authority: str,
        generation: int,
        confidence: float,
        observed_at: float,
    ) -> None:
        if not str(scope_id).strip() or not str(source_authority).strip():
            raise ValueError("scope_id and source_authority are required")
        if generation < 1:
            raise ValueError("generation must be positive")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not isinstance(observed_at, (int, float)):
            raise ValueError("observed_at must be numeric")

    def record_observation(
        self,
        *,
        scope_id: str,
        entity_type: str,
        entity_id: str,
        source_authority: str,
        generation: int,
        confidence: float,
        observed_at: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate(
            scope_id=scope_id,
            source_authority=source_authority,
            generation=generation,
            confidence=confidence,
            observed_at=observed_at,
        )
        if not str(entity_type).strip() or not str(entity_id).strip():
            raise ValueError("entity_type and entity_id are required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        observation_id = self._identity(
            "observation",
            (scope_id, entity_type, entity_id, source_authority, generation, observed_at),
        )
        encoded = json.dumps(payload, sort_keys=True)
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO healing_evidence_observations(
                    observation_id,scope_id,entity_type,entity_id,source_authority,
                    generation,confidence,observed_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id, scope_id, entity_type, entity_id,
                    source_authority, generation, float(confidence),
                    float(observed_at), encoded,
                ),
            )
            row = db.execute(
                "SELECT * FROM healing_evidence_observations WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
        return self._observation(row)

    def record_relationship(
        self,
        *,
        scope_id: str,
        source_type: str,
        source_id: str,
        relation: str,
        target_type: str,
        target_id: str,
        source_authority: str,
        generation: int,
        confidence: float,
        observed_at: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate(
            scope_id=scope_id,
            source_authority=source_authority,
            generation=generation,
            confidence=confidence,
            observed_at=observed_at,
        )
        if not all(str(value).strip() for value in (source_type, source_id, relation, target_type, target_id)):
            raise ValueError("relationship identity fields are required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        relationship_id = self._identity(
            "relationship",
            (scope_id, source_type, source_id, relation, target_type, target_id, source_authority, generation),
        )
        encoded = json.dumps(payload, sort_keys=True)
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO healing_evidence_relationships(
                    relationship_id,scope_id,source_type,source_id,relation,
                    target_type,target_id,source_authority,generation,
                    confidence,observed_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    relationship_id, scope_id, source_type, source_id, relation,
                    target_type, target_id, source_authority, generation,
                    float(confidence), float(observed_at), encoded,
                ),
            )
            row = db.execute(
                "SELECT * FROM healing_evidence_relationships WHERE relationship_id=?",
                (relationship_id,),
            ).fetchone()
        return self._relationship(row)

    def observations(self, *, scope_id: str | None = None) -> tuple[dict[str, Any], ...]:
        with self._connect() as db:
            if scope_id is None:
                rows = db.execute(
                    "SELECT * FROM healing_evidence_observations ORDER BY observed_at,observation_id"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM healing_evidence_observations WHERE scope_id=? ORDER BY observed_at,observation_id",
                    (scope_id,),
                ).fetchall()
        return tuple(self._observation(row) for row in rows)

    def relationships(self, *, scope_id: str | None = None) -> tuple[dict[str, Any], ...]:
        with self._connect() as db:
            if scope_id is None:
                rows = db.execute(
                    "SELECT * FROM healing_evidence_relationships ORDER BY observed_at,relationship_id"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM healing_evidence_relationships WHERE scope_id=? ORDER BY observed_at,relationship_id",
                    (scope_id,),
                ).fetchall()
        return tuple(self._relationship(row) for row in rows)

    def snapshot(self, scope_id: str) -> dict[str, Any]:
        observations = self.observations(scope_id=scope_id)
        relationships = self.relationships(scope_id=scope_id)
        path_ids = set()
        for row in observations:
            payload = row["payload"]
            path_id = payload.get("fabric_path_id")
            if path_id:
                path_ids.add(str(path_id))
            if row["entity_type"] == "fabric_path":
                path_ids.add(row["entity_id"])
        for row in relationships:
            payload = row["payload"]
            path_id = payload.get("fabric_path_id")
            if path_id:
                path_ids.add(str(path_id))
        return {
            "scope_id": scope_id,
            "observations": observations,
            "relationships": relationships,
            "path_ids": tuple(sorted(path_ids)),
        }

    @staticmethod
    def _observation(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    @staticmethod
    def _relationship(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result
