"""Quorum-replicated durable healing state with fencing and crash-safe replay.

The replication layer is deliberately above HealingState. HealingState remains the
schema and lifecycle authority for healing records, while this module provides
write-ahead replication, quorum commit, leader fencing, reconciliation, and
explicit replica repair.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from .healing_state import HealingState, HealingStateError


class HealingReplicationError(RuntimeError):
    """Raised when replicated healing state cannot safely make progress."""


class ReplicatedHealingState:
    """Replicate HealingState mutations across a fixed odd-sized replica set.

    A mutation is committed only after a majority has durably recorded the same
    hash-chained log entry. State projection can lag a committed log entry after
    a crash and is repaired by reconciliation. A minority partition cannot
    mutate healing state or acquire controller authority.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS healing_replication_meta(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        replica_id TEXT NOT NULL,
        cluster_id TEXT NOT NULL,
        commit_index INTEGER NOT NULL DEFAULT 0,
        applied_index INTEGER NOT NULL DEFAULT 0,
        generation INTEGER NOT NULL DEFAULT 0,
        leader_id TEXT NOT NULL DEFAULT '',
        fencing_token INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS healing_replication_log(
        log_index INTEGER PRIMARY KEY,
        generation INTEGER NOT NULL,
        command_id TEXT NOT NULL UNIQUE,
        command TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        prev_checksum TEXT NOT NULL,
        checksum TEXT NOT NULL,
        committed INTEGER NOT NULL DEFAULT 1,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_healing_replication_log_generation
        ON healing_replication_log(generation, log_index);
    CREATE TABLE IF NOT EXISTS healing_replication_projections(
        name TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        generation INTEGER NOT NULL,
        fencing_token INTEGER NOT NULL,
        updated_at REAL NOT NULL
    );
    """

    def __init__(self, replica_paths: tuple[str, ...] | list[str], *, cluster_id: str = "healing-cluster"):
        paths = tuple(str(path) for path in replica_paths)
        if len(paths) < 3 or len(paths) % 2 == 0:
            raise ValueError("an odd replica count of at least three is required")
        if any(not path.strip() for path in paths):
            raise ValueError("replica paths must be non-empty")
        if len(set(paths)) != len(paths):
            raise ValueError("replica paths must be unique")
        if not cluster_id.strip():
            raise ValueError("cluster_id is required")

        self.replica_paths = paths
        self.cluster_id = cluster_id
        self._available = [True] * len(paths)
        self._states = [HealingState(path) for path in paths]
        self._initialize_replication()

    @property
    def quorum(self) -> int:
        return len(self.replica_paths) // 2 + 1

    def _connect(self, index: int) -> sqlite3.Connection:
        db = sqlite3.connect(self.replica_paths[index], timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _initialize_replication(self) -> None:
        now = time.time()
        for index in range(len(self.replica_paths)):
            with self._connect(index) as db:
                db.executescript(self._SCHEMA)
                row = db.execute(
                    "SELECT singleton FROM healing_replication_meta WHERE singleton=1"
                ).fetchone()
                if not row:
                    db.execute(
                        """INSERT INTO healing_replication_meta
                           (singleton,replica_id,cluster_id,updated_at)
                           VALUES(1,?,?,?)""",
                        (f"replica-{index}", self.cluster_id, now),
                    )
                else:
                    meta = db.execute(
                        "SELECT cluster_id FROM healing_replication_meta WHERE singleton=1"
                    ).fetchone()
                    if meta["cluster_id"] != self.cluster_id:
                        raise HealingReplicationError("replica belongs to another healing cluster")

    def set_replica_available(self, index: int, available: bool) -> None:
        if index < 0 or index >= len(self.replica_paths):
            raise IndexError("unknown replica")
        self._available[index] = bool(available)

    def _available_indexes(self) -> tuple[int, ...]:
        return tuple(i for i, available in enumerate(self._available) if available)

    def _require_quorum(self) -> tuple[int, ...]:
        indexes = self._available_indexes()
        if len(indexes) < self.quorum:
            raise HealingReplicationError(
                f"quorum unavailable: {len(indexes)} available, {self.quorum} required"
            )
        return indexes

    @staticmethod
    def _canonical_payload(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _checksum(
        log_index: int,
        generation: int,
        command_id: str,
        command: str,
        payload_json: str,
        prev_checksum: str,
    ) -> str:
        material = "\0".join(
            (
                str(log_index),
                str(generation),
                command_id,
                command,
                payload_json,
                prev_checksum,
            )
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def _meta(self, index: int) -> dict[str, Any]:
        with self._connect(index) as db:
            row = db.execute(
                "SELECT * FROM healing_replication_meta WHERE singleton=1"
            ).fetchone()
            if not row:
                raise HealingReplicationError("replica metadata is missing")
            return dict(row)

    def _log_entry(self, index: int, log_index: int) -> dict[str, Any] | None:
        with self._connect(index) as db:
            row = db.execute(
                "SELECT * FROM healing_replication_log WHERE log_index=?",
                (log_index,),
            ).fetchone()
            return dict(row) if row else None

    def _validate_chain(self, index: int, through: int | None = None) -> None:
        meta = self._meta(index)
        limit = int(meta["commit_index"] if through is None else through)
        previous = ""
        with self._connect(index) as db:
            rows = db.execute(
                "SELECT * FROM healing_replication_log WHERE log_index<=? ORDER BY log_index",
                (limit,),
            ).fetchall()
        if len(rows) != limit:
            raise HealingReplicationError(f"replica {index} has an incomplete committed log")
        for row in rows:
            expected = self._checksum(
                int(row["log_index"]),
                int(row["generation"]),
                row["command_id"],
                row["command"],
                row["payload_json"],
                previous,
            )
            if row["prev_checksum"] != previous or row["checksum"] != expected:
                raise HealingReplicationError(f"replica {index} checksum conflict")
            previous = row["checksum"]

    def _quorum_canonical(self) -> tuple[int, dict[str, Any]]:
        indexes = self._require_quorum()
        metas = [(index, self._meta(index)) for index in indexes]
        highest = max(int(meta["commit_index"]) for _, meta in metas)
        candidates = [
            (index, meta)
            for index, meta in metas
            if int(meta["commit_index"]) == highest
        ]
        if len(candidates) < self.quorum:
            raise HealingReplicationError("no quorum agrees on committed index")
        canonical_index = candidates[0][0]
        self._validate_chain(canonical_index, highest)
        canonical = self._log_entry(canonical_index, highest) if highest else None
        for index, _ in candidates[1:]:
            self._validate_chain(index, highest)
            if highest and self._log_entry(index, highest)["checksum"] != canonical["checksum"]:
                raise HealingReplicationError("quorum checksum conflict")
        return canonical_index, canonical or {}

    def leadership(self) -> dict[str, Any]:
        indexes = self._require_quorum()
        metas = [self._meta(index) for index in indexes]
        generations = {int(meta["generation"]) for meta in metas}
        leaders = {(meta["leader_id"], int(meta["fencing_token"])) for meta in metas}
        if len(generations) != 1 or len(leaders) != 1:
            raise HealingReplicationError("replicated leadership state is inconsistent")
        result = metas[0]
        result["quorum"] = len(indexes)
        return result

    def acquire_leadership(self, controller_id: str, *, generation: int, now: float | None = None) -> dict[str, Any]:
        if not controller_id.strip() or generation < 1:
            raise ValueError("controller_id and positive generation are required")
        now = time.time() if now is None else float(now)
        indexes = self._require_quorum()
        metas = [self._meta(index) for index in indexes]
        current_generation = max(int(meta["generation"]) for meta in metas)
        current_token = max(int(meta["fencing_token"]) for meta in metas)
        if generation <= current_generation:
            raise HealingReplicationError("generation is not newer than current authority")
        token = current_token + 1
        for index in indexes:
            with self._connect(index) as db:
                db.execute(
                    """UPDATE healing_replication_meta
                       SET generation=?,leader_id=?,fencing_token=?,updated_at=?
                       WHERE singleton=1""",
                    (generation, controller_id, token, now),
                )
        return self.leadership()

    def _assert_leader(self, controller_id: str, fencing_token: int) -> dict[str, Any]:
        meta = self.leadership()
        if meta["leader_id"] != controller_id or int(meta["fencing_token"]) != int(fencing_token):
            raise HealingReplicationError("fenced controller")
        return meta

    def _append_and_apply(
        self,
        *,
        command: str,
        payload: Mapping[str, Any],
        controller_id: str,
        fencing_token: int,
        now: float,
    ) -> dict[str, Any]:
        meta = self._assert_leader(controller_id, fencing_token)
        indexes = self._require_quorum()
        base = int(meta["commit_index"])
        canonical_replica, canonical_entry = self._quorum_canonical()
        canonical_commit_index = int(self._meta(canonical_replica)["commit_index"])
        if canonical_commit_index != base:
            raise HealingReplicationError("replication index changed during mutation")
        previous = canonical_entry.get("checksum", "") if base else ""
        log_index = base + 1
        payload_json = self._canonical_payload(payload)
        command_id = hashlib.sha256(
            f"{self.cluster_id}\0{log_index}\0{meta['generation']}\0{command}\0{payload_json}".encode()
        ).hexdigest()
        checksum = self._checksum(
            log_index,
            int(meta["generation"]),
            command_id,
            command,
            payload_json,
            previous,
        )
        entry = {
            "log_index": log_index,
            "generation": int(meta["generation"]),
            "command_id": command_id,
            "command": command,
            "payload_json": payload_json,
            "prev_checksum": previous,
            "checksum": checksum,
            "committed": 1,
            "created_at": now,
        }

        for index in indexes:
            with self._connect(index) as db:
                db.execute(
                    """INSERT OR IGNORE INTO healing_replication_log
                       (log_index,generation,command_id,command,payload_json,prev_checksum,checksum,committed,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    tuple(entry.values()),
                )
                existing = db.execute(
                    "SELECT checksum FROM healing_replication_log WHERE log_index=?",
                    (log_index,),
                ).fetchone()
                if not existing or existing["checksum"] != checksum:
                    raise HealingReplicationError(f"replica {index} rejected quorum log entry")
                db.execute(
                    "UPDATE healing_replication_meta SET commit_index=?,generation=?,leader_id=?,fencing_token=?,updated_at=? WHERE singleton=1",
                    (log_index, int(meta["generation"]), controller_id, fencing_token, now),
                )

        applied = 0
        for index in indexes:
            try:
                self._apply_until(index, log_index)
                applied += 1
            except Exception:
                continue
        if applied < self.quorum:
            raise HealingReplicationError(
                f"quorum committed log entry {log_index}, but only {applied} replicas applied it"
            )
        return self._result(log_index)

    def _apply_until(self, index: int, target: int) -> None:
        meta = self._meta(index)
        start = int(meta["applied_index"]) + 1
        if start > target:
            return
        with self._connect(index) as db:
            rows = db.execute(
                "SELECT * FROM healing_replication_log WHERE log_index BETWEEN ? AND ? ORDER BY log_index",
                (start, target),
            ).fetchall()
        if len(rows) != target - start + 1:
            raise HealingReplicationError(f"replica {index} is missing committed entries")
        for row in rows:
            payload = json.loads(row["payload_json"])
            self._apply_command(index, row["command"], payload)
        with self._connect(index) as db:
            db.execute(
                "UPDATE healing_replication_meta SET applied_index=?,updated_at=? WHERE singleton=1",
                (target, time.time()),
            )

    def _apply_command(self, index: int, command: str, payload: Mapping[str, Any]) -> None:
        state = self._states[index]
        if command == "ensure_action":
            state.ensure_action(
                scope_id=str(payload["scope_id"]),
                failure_fingerprint=str(payload["failure_fingerprint"]),
                generation=int(payload["generation"]),
                strategy=str(payload["strategy"]),
            )
            return
        if command == "claim_action":
            action_id = str(payload["action_id"])
            current = state.action(action_id)
            if (
                current.get("owner") == payload["owner"]
                and int(current.get("fencing_token") or 0) >= int(payload["fencing_token"])
            ):
                return
            state.claim_action(
                action_id,
                owner=str(payload["owner"]),
                now=float(payload["now"]),
                lease_seconds=float(payload["lease_seconds"]),
            )
            return
        if command == "checkpoint":
            current = state.action(str(payload["action_id"]))
            if current.get("checkpoint") == payload["checkpoint"] and current.get("owner") == payload["owner"]:
                return
            state.checkpoint(
                action_id=str(payload["action_id"]),
                owner=str(payload["owner"]),
                checkpoint=str(payload["checkpoint"]),
                payload=dict(payload["payload"]),
                now=float(payload["now"]),
            )
            return
        if command == "record_reconciliation":
            state.record_reconciliation(
                action_id=str(payload["action_id"]),
                authoritative_state=dict(payload["authoritative_state"]),
                observed_at=float(payload["observed_at"]),
            )
            return
        if command == "enter_degraded":
            state.enter_degraded(
                scope_id=str(payload["scope_id"]),
                reason=str(payload["reason"]),
                now=float(payload["now"]),
            )
            return
        if command == "projection":
            with self._connect(index) as db:
                db.execute(
                    """INSERT INTO healing_replication_projections(
                           name,payload_json,generation,fencing_token,updated_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET
                           payload_json=excluded.payload_json,
                           generation=excluded.generation,
                           fencing_token=excluded.fencing_token,
                           updated_at=excluded.updated_at""",
                    (
                        str(payload["name"]),
                        self._canonical_payload(payload["value"]),
                        int(payload["generation"]),
                        int(payload["fencing_token"]),
                        float(payload["updated_at"]),
                    ),
                )
            return
        raise HealingReplicationError(f"unknown replication command: {command}")

    def _result(self, commit_index: int) -> dict[str, Any]:
        meta = self.leadership()
        meta["commit_index"] = commit_index
        meta["replicas"] = [
            {
                "replica": index,
                "available": self._available[index],
                **self._meta(index),
            }
            for index in range(len(self.replica_paths))
        ]
        return meta

    def commit_index(self) -> int:
        return int(self.leadership()["commit_index"])

    def ensure_action(self, *, scope_id: str, failure_fingerprint: str, generation: int,
                      strategy: str, controller_id: str, fencing_token: int,
                      now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        self._append_and_apply(
            command="ensure_action",
            payload={
                "scope_id": scope_id,
                "failure_fingerprint": failure_fingerprint,
                "generation": generation,
                "strategy": strategy,
            },
            controller_id=controller_id,
            fencing_token=fencing_token,
            now=now,
        )
        action = self._states[0].ensure_action(
            scope_id=scope_id,
            failure_fingerprint=failure_fingerprint,
            generation=generation,
            strategy=strategy,
        )
        return action

    def claim_action(self, action_id: str, *, owner: str, controller_id: str,
                     fencing_token: int, now: float | None = None,
                     lease_seconds: float = 300.0) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        self._append_and_apply(
            command="claim_action",
            payload={
                "action_id": action_id,
                "owner": owner,
                "fencing_token": int(fencing_token),
                "now": now,
                "lease_seconds": lease_seconds,
            },
            controller_id=controller_id,
            fencing_token=fencing_token,
            now=now,
        )
        return self._states[0].action(action_id)

    def checkpoint(self, *, action_id: str, owner: str, checkpoint: str,
                   payload: Mapping[str, Any], controller_id: str,
                   fencing_token: int, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        self._append_and_apply(
            command="checkpoint",
            payload={
                "action_id": action_id,
                "owner": owner,
                "checkpoint": checkpoint,
                "payload": dict(payload),
                "now": now,
            },
            controller_id=controller_id,
            fencing_token=fencing_token,
            now=now,
        )
        return self._states[0].action(action_id)

    def record_reconciliation(self, *, action_id: str,
                              authoritative_state: Mapping[str, Any],
                              observed_at: float, controller_id: str,
                              fencing_token: int, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        self._append_and_apply(
            command="record_reconciliation",
            payload={
                "action_id": action_id,
                "authoritative_state": dict(authoritative_state),
                "observed_at": float(observed_at),
            },
            controller_id=controller_id,
            fencing_token=fencing_token,
            now=now,
        )
        return self._states[0].action(action_id)

    def enter_degraded(self, *, scope_id: str, reason: str, controller_id: str,
                       fencing_token: int, now: float | None = None) -> None:
        now = time.time() if now is None else float(now)
        self._append_and_apply(
            command="enter_degraded",
            payload={"scope_id": scope_id, "reason": reason, "now": now},
            controller_id=controller_id,
            fencing_token=fencing_token,
            now=now,
        )

    def record_projection(
        self,
        *,
        name: str,
        value: Mapping[str, Any],
        controller_id: str,
        fencing_token: int,
        now: float | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        meta = self._assert_leader(controller_id, fencing_token)
        self._append_and_apply(
            command="projection",
            payload={
                "name": name,
                "value": dict(value),
                "generation": int(meta["generation"]),
                "fencing_token": int(fencing_token),
                "updated_at": now,
            },
            controller_id=controller_id,
            fencing_token=fencing_token,
            now=now,
        )
        return self.projection(name)

    def projection(self, name: str) -> dict[str, Any] | None:
        self.reconcile()
        with self._connect(0) as db:
            row = db.execute(
                "SELECT * FROM healing_replication_projections WHERE name=?",
                (name,),
            ).fetchone()
        if not row:
            return None
        return {
            "name": row["name"],
            "value": json.loads(row["payload_json"]),
            "generation": int(row["generation"]),
            "fencing_token": int(row["fencing_token"]),
            "updated_at": float(row["updated_at"]),
        }

    def action(self, action_id: str) -> dict[str, Any]:
        self.reconcile()
        return self._states[0].action(action_id)

    def list_actions(self) -> list[dict[str, Any]]:
        self.reconcile()
        return self._states[0].list_actions()

    def degraded_scope(self, scope_id: str) -> dict[str, Any] | None:
        self.reconcile()
        return self._states[0].degraded_scope(scope_id)

    def reconcile(self) -> dict[str, Any]:
        indexes = self._require_quorum()
        canonical, canonical_entry = self._quorum_canonical()
        highest = int(self._meta(canonical)["commit_index"])
        canonical_entries: list[dict[str, Any]] = []
        with self._connect(canonical) as db:
            canonical_entries = [dict(row) for row in db.execute(
                "SELECT * FROM healing_replication_log WHERE log_index<=? ORDER BY log_index",
                (highest,),
            ).fetchall()]

        for index in range(len(self.replica_paths)):
            if not self._available[index] or index == canonical:
                continue
            self._repair_log_from_canonical(index, canonical, canonical_entries)
            self._apply_until(index, highest)

        result = {
            "commit_index": highest,
            "canonical_replica": canonical,
            "replicas": [
                {
                    "replica": index,
                    "available": self._available[index],
                    **self._meta(index),
                }
                for index in range(len(self.replica_paths))
            ],
        }
        return result

    def _repair_log_from_canonical(
        self,
        index: int,
        canonical_index: int,
        entries: list[dict[str, Any]],
    ) -> None:
        with self._connect(index) as db:
            current = db.execute(
                "SELECT log_index,checksum FROM healing_replication_log ORDER BY log_index"
            ).fetchall()
            current_by_index = {int(row["log_index"]): row["checksum"] for row in current}
            for entry in entries:
                existing = current_by_index.get(int(entry["log_index"]))
                if existing is not None and existing != entry["checksum"]:
                    self._reset_healing_projection(index)
                    db.execute("DELETE FROM healing_replication_log")
                    break
            for entry in entries:
                db.execute(
                    """INSERT OR REPLACE INTO healing_replication_log
                       (log_index,generation,command_id,command,payload_json,prev_checksum,checksum,committed,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        entry["log_index"], entry["generation"], entry["command_id"],
                        entry["command"], entry["payload_json"], entry["prev_checksum"],
                        entry["checksum"], entry["committed"], entry["created_at"],
                    ),
                )
            canonical_meta = self._meta(canonical_index)
            db.execute(
                "UPDATE healing_replication_meta SET commit_index=?,generation=?,leader_id=?,fencing_token=?,updated_at=? WHERE singleton=1",
                (
                    len(entries),
                    int(canonical_meta["generation"]),
                    str(canonical_meta["leader_id"]),
                    int(canonical_meta["fencing_token"]),
                    time.time(),
                ),
            )

    def _reset_healing_projection(self, index: int) -> None:
        with self._connect(index) as db:
            for table in (
                "healing_checkpoints",
                "healing_reconciliations",
                "healing_events",
                "healing_degraded",
                "healing_actions",
            ):
                db.execute(f"DELETE FROM {table}")
            db.execute(
                "UPDATE healing_replication_meta SET applied_index=0 WHERE singleton=1"
            );

    def repair_replica(self, index: int) -> dict[str, Any]:
        if index < 0 or index >= len(self.replica_paths):
            raise IndexError("unknown replica")
        self._require_quorum()
        self._available[index] = True
        result = self.reconcile()
        self._validate_chain(index, int(result["commit_index"]))
        return result

    def snapshot(self) -> dict[str, Any]:
        self.reconcile()
        return {
            "cluster_id": self.cluster_id,
            "quorum": self.quorum,
            "leadership": self.leadership(),
            "commit_index": self.commit_index(),
            "replicas": [
                {
                    "replica": index,
                    "available": self._available[index],
                    **self._meta(index),
                }
                for index in range(len(self.replica_paths))
            ],
        }
