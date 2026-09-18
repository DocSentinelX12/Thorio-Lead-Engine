"""Durable provider-neutral physical resource inventory.

This inventory records observed compute resources and their evidence. It is
deliberately separate from the authoritative Thorio work queue.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import asdict
from typing import Any

from .compute_provider import ProviderResourceSnapshot
from .compute_resources import GpuResource, NodeResource, ResourceState


class ComputeInventory:
    """SQLite-backed resource inventory with stable physical identities."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            data_dir = os.environ.get("LEAD_ENGINE_DATA_DIR", "data")
            db_path = os.environ.get(
                "THORIO_COMPUTE_INVENTORY_DB",
                os.path.join(data_dir, "leads.sqlite3"),
            )
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_resource_inventory (
                resource_key TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                gpu_id TEXT,
                identity_key TEXT,
                resource_type TEXT NOT NULL,
                state TEXT NOT NULL,
                observed_at REAL NOT NULL,
                expires_at REAL,
                ephemeral INTEGER NOT NULL DEFAULT 0,
                authentication_state TEXT NOT NULL DEFAULT 'unknown',
                payload_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                first_seen_at REAL NOT NULL,
                last_seen_at REAL NOT NULL)""")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(compute_resource_inventory)").fetchall()}
            if "authentication_state" not in columns:
                connection.execute(
                    "ALTER TABLE compute_resource_inventory "
                    "ADD COLUMN authentication_state TEXT NOT NULL DEFAULT 'unknown'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_inventory_provider "
                "ON compute_resource_inventory(provider_id,domain_id,node_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_inventory_state "
                "ON compute_resource_inventory(state)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_allocations (
                allocation_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                resource_keys_json TEXT NOT NULL,
                task_id TEXT,
                attempt_id TEXT,
                generation INTEGER,
                lease_token_digest TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                released_at REAL,
                release_reason TEXT NOT NULL DEFAULT ''
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_allocations_binding "
                "ON compute_allocations(task_id,attempt_id,generation)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_allocations_state "
                "ON compute_allocations(state,updated_at)"
            )
            connection.commit()

    @staticmethod
    def _node_payload(node: NodeResource) -> dict[str, Any]:
        payload = asdict(node)
        payload["state"] = node.state.value
        payload["gpus"] = []
        for gpu in node.gpus:
            item = asdict(gpu)
            item["health_state"] = gpu.health_state.value
            item["availability_state"] = gpu.availability_state.value
            payload["gpus"].append(item)
        return payload

    @staticmethod
    def _resource_key(provider_id: str, domain_id: str, node_id: str, gpu: GpuResource | None) -> str:
        if gpu is None:
            return f"{provider_id}/{domain_id}/{node_id}/cpu"
        return f"{provider_id}/{domain_id}/{node_id}/gpu/{gpu.identity_key}"

    def observe(self, snapshot: ProviderResourceSnapshot) -> dict[str, Any]:
        """Persist one provider observation without deleting historical resources."""
        now = time.time()
        rows: list[tuple[str, str, str, str, str | None, str | None, str, str, float, float | None, int, str, str, str, float, float]] = []
        for node in snapshot.nodes:
            node_payload = self._node_payload(node)
            rows.append((
                self._resource_key(snapshot.provider_id, snapshot.domain_id, node.node_id, None),
                snapshot.provider_id, snapshot.domain_id, node.node_id, None, None, "cpu",
                node.state.value, snapshot.observed_at, snapshot.expires_at, int(snapshot.ephemeral), snapshot.authentication_state,
                json.dumps(node_payload, ensure_ascii=False, sort_keys=True),
                json.dumps(dict(snapshot.evidence or {}), ensure_ascii=False, sort_keys=True), now, now,
            ))
            for gpu in node.gpus:
                rows.append((
                    self._resource_key(snapshot.provider_id, snapshot.domain_id, node.node_id, gpu),
                    snapshot.provider_id, snapshot.domain_id, node.node_id, gpu.gpu_id, gpu.identity_key,
                    "gpu", gpu.availability_state.value, snapshot.observed_at, snapshot.expires_at,
                    int(snapshot.ephemeral), snapshot.authentication_state, json.dumps(asdict(gpu) | {
                        "health_state": gpu.health_state.value,
                        "availability_state": gpu.availability_state.value,
                    }, ensure_ascii=False, sort_keys=True),
                    json.dumps(dict(snapshot.evidence or {}), ensure_ascii=False, sort_keys=True), now, now,
                ))
        with self._connect() as connection:
            for row in rows:
                connection.execute("""INSERT INTO compute_resource_inventory
                    (resource_key,provider_id,domain_id,node_id,gpu_id,identity_key,
                     resource_type,state,observed_at,expires_at,ephemeral,authentication_state,payload_json,
                     evidence_json,first_seen_at,last_seen_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(resource_key) DO UPDATE SET
                    provider_id=excluded.provider_id,domain_id=excluded.domain_id,
                    node_id=excluded.node_id,gpu_id=excluded.gpu_id,
                    identity_key=excluded.identity_key,state=excluded.state,
                    observed_at=excluded.observed_at,expires_at=excluded.expires_at,
                    ephemeral=excluded.ephemeral,authentication_state=excluded.authentication_state,
                    payload_json=excluded.payload_json,
                    evidence_json=excluded.evidence_json,last_seen_at=excluded.last_seen_at""", row)
            connection.commit()
        return {"provider_id": snapshot.provider_id, "domain_id": snapshot.domain_id,
                "observed_nodes": len(snapshot.nodes),
                "observed_gpus": sum(node.gpu_count for node in snapshot.nodes)}

    def mark_provider_missing(self, provider_id: str, domain_id: str, *, observed_at: float | None = None) -> int:
        """Withdraw a disappeared provider from eligibility without deleting history.

        Reserved resources remain reserved until their durable allocation is
        explicitly released or recovered.
        """
        when = time.time() if observed_at is None else observed_at
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE compute_resource_inventory SET state=?,last_seen_at=? "
                "WHERE provider_id=? AND domain_id=? "
                "AND state NOT IN (?,?)",
                (ResourceState.DEGRADED.value, when, provider_id, domain_id,
                 ResourceState.QUARANTINED.value, ResourceState.RESERVED.value),
            )
            connection.commit()
            return cursor.rowcount

    def eligible(self, *, now: float | None = None) -> list[dict[str, Any]]:
        current = time.time() if now is None else now
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM compute_resource_inventory "
                "WHERE state IN (?,?) AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY provider_id,domain_id,node_id,resource_type,resource_key",
                (ResourceState.HEALTHY.value, ResourceState.AVAILABLE.value, current),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, resource_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_resource_inventory WHERE resource_key=?", (resource_key,)
            ).fetchone()
        return dict(row) if row else None

    def mark_state(self, resource_key: str, state: ResourceState) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE compute_resource_inventory SET state=?,last_seen_at=? WHERE resource_key=?",
                (state.value, time.time(), resource_key),
            )
            connection.commit()
            return cursor.rowcount == 1

    def resources(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM compute_resource_inventory ORDER BY provider_id,domain_id,node_id,resource_key"
            ).fetchall()
        return [dict(row) for row in rows]

    def record_allocation(
        self,
        allocation_id: str,
        provider_id: str,
        domain_id: str,
        resource_keys: list[str] | tuple[str, ...],
    ) -> None:
        """Persist ownership of already-reserved physical resources."""
        keys = tuple(dict.fromkeys(str(key) for key in resource_keys))
        if not allocation_id.strip() or not provider_id.strip() or not domain_id.strip() or not keys:
            raise ValueError("allocation identity and resources are required")
        now = time.time()
        serialized = json.dumps(keys, ensure_ascii=False)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT provider_id,domain_id,resource_keys_json,state FROM compute_allocations WHERE allocation_id=?",
                (allocation_id,),
            ).fetchone()
            if existing:
                if (existing["provider_id"] != provider_id or existing["domain_id"] != domain_id
                        or tuple(json.loads(existing["resource_keys_json"])) != keys):
                    raise ValueError("allocation_id already exists with different resources")
                return
            rows = connection.execute(
                f"SELECT resource_key,state,provider_id,domain_id FROM compute_resource_inventory "
                f"WHERE resource_key IN ({','.join('?' for _ in keys)})", keys).fetchall()
            by_key = {row["resource_key"]: row for row in rows}
            if len(by_key) != len(keys) or any(
                row["state"] != ResourceState.RESERVED.value
                or row["provider_id"] != provider_id or row["domain_id"] != domain_id
                for row in by_key.values()):
                raise ValueError("allocation resources are not reserved")
            connection.execute(
                """INSERT INTO compute_allocations
                   (allocation_id,state,provider_id,domain_id,resource_keys_json,created_at,updated_at)
                   VALUES (?, 'reserved', ?, ?, ?, ?, ?)""",
                (allocation_id, provider_id, domain_id, serialized, now, now),
            )
            connection.commit()

    def bind_allocation(
        self,
        allocation_id: str,
        *,
        task_id: str,
        attempt_id: str,
        generation: int,
        lease_token_digest: str,
    ) -> bool:
        """Bind a physical allocation to one exact execution attempt."""
        if generation < 1 or not task_id.strip() or not attempt_id.strip() or not lease_token_digest.strip():
            raise ValueError("complete execution binding is required")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state,task_id,attempt_id,generation FROM compute_allocations WHERE allocation_id=?",
                (allocation_id,),
            ).fetchone()
            if not row:
                connection.rollback()
                return False
            if row["state"] == "bound":
                same = row["task_id"] == task_id and row["attempt_id"] == attempt_id and int(row["generation"]) == generation
                connection.rollback()
                return same
            if row["state"] != "reserved" or row["task_id"] is not None:
                connection.rollback()
                return False
            cursor = connection.execute(
                """UPDATE compute_allocations
                   SET state='bound',task_id=?,attempt_id=?,generation=?,
                       lease_token_digest=?,updated_at=?
                   WHERE allocation_id=? AND state='reserved' AND task_id IS NULL""",
                (task_id, attempt_id, generation, lease_token_digest, now, allocation_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            connection.commit()
            return True

    def allocation(self, allocation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_allocations WHERE allocation_id=?", (allocation_id,)
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["resource_keys"] = json.loads(item.pop("resource_keys_json"))
        return item

    def release_allocation(
        self,
        allocation_id: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        generation: int | None = None,
        reason: str = "",
    ) -> int:
        """Release only resources owned by the exact allocation binding."""
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM compute_allocations WHERE allocation_id=?", (allocation_id,)
            ).fetchone()
            if not row or row["state"] not in {"reserved", "bound"}:
                connection.rollback()
                return 0
            if task_id is not None and row["task_id"] != task_id:
                connection.rollback()
                return 0
            if attempt_id is not None and row["attempt_id"] != attempt_id:
                connection.rollback()
                return 0
            if generation is not None and int(row["generation"] or 0) != generation:
                connection.rollback()
                return 0
            keys = json.loads(row["resource_keys_json"])
            cursor = connection.execute(
                f"UPDATE compute_resource_inventory SET state=?,last_seen_at=? "
                f"WHERE resource_key IN ({','.join('?' for _ in keys)}) AND state=?",
                (ResourceState.AVAILABLE.value, now, *keys, ResourceState.RESERVED.value),
            )
            connection.execute(
                """UPDATE compute_allocations
                   SET state='released',updated_at=?,released_at=?,release_reason=?
                   WHERE allocation_id=?""",
                (now, now, str(reason)[:4000], allocation_id),
            )
            connection.commit()
            return cursor.rowcount

    def allocations(self, *, state: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM compute_allocations"
        args: tuple[Any, ...] = ()
        if state is not None:
            query += " WHERE state=?"
            args = (state,)
        query += " ORDER BY created_at,allocation_id"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["resource_keys"] = json.loads(item.pop("resource_keys_json"))
            result.append(item)
        return result

