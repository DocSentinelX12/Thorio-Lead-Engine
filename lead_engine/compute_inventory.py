"""Durable provider-neutral physical resource inventory.

This inventory records observed compute resources and their evidence. It is
deliberately separate from the authoritative Thorio work queue.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from typing import Any, Iterable, Mapping

from .compute_provider import ProviderResourceSnapshot
from .compute_resources import GpuResource, NodeResource, ResourceState


class ComputeInventory:
    """SQLite-backed resource inventory with stable physical identities."""

    def __init__(self, db_path: str = "data/lead_engine.db"):
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
                payload_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                first_seen_at REAL NOT NULL,
                last_seen_at REAL NOT NULL)""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_inventory_provider "
                "ON compute_resource_inventory(provider_id,domain_id,node_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_inventory_state "
                "ON compute_resource_inventory(state)"
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
        rows: list[tuple[str, str, str, str, str | None, str | None, str, str, float, float | None, int, str, str, float, float]] = []
        for node in snapshot.nodes:
            node_payload = self._node_payload(node)
            rows.append((
                self._resource_key(snapshot.provider_id, snapshot.domain_id, node.node_id, None),
                snapshot.provider_id, snapshot.domain_id, node.node_id, None, None, "cpu",
                node.state.value, snapshot.observed_at, snapshot.expires_at, int(snapshot.ephemeral),
                json.dumps(node_payload, ensure_ascii=False, sort_keys=True),
                json.dumps(dict(snapshot.evidence or {}), ensure_ascii=False, sort_keys=True), now, now,
            ))
            for gpu in node.gpus:
                rows.append((
                    self._resource_key(snapshot.provider_id, snapshot.domain_id, node.node_id, gpu),
                    snapshot.provider_id, snapshot.domain_id, node.node_id, gpu.gpu_id, gpu.identity_key,
                    "gpu", gpu.availability_state.value, snapshot.observed_at, snapshot.expires_at,
                    int(snapshot.ephemeral), json.dumps(asdict(gpu) | {
                        "health_state": gpu.health_state.value,
                        "availability_state": gpu.availability_state.value,
                    }, ensure_ascii=False, sort_keys=True),
                    json.dumps(dict(snapshot.evidence or {}), ensure_ascii=False, sort_keys=True), now, now,
                ))
        with self._connect() as connection:
            for row in rows:
                connection.execute("""INSERT INTO compute_resource_inventory
                    (resource_key,provider_id,domain_id,node_id,gpu_id,identity_key,
                     resource_type,state,observed_at,expires_at,ephemeral,payload_json,
                     evidence_json,first_seen_at,last_seen_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(resource_key) DO UPDATE SET
                    provider_id=excluded.provider_id,domain_id=excluded.domain_id,
                    node_id=excluded.node_id,gpu_id=excluded.gpu_id,
                    identity_key=excluded.identity_key,state=excluded.state,
                    observed_at=excluded.observed_at,expires_at=excluded.expires_at,
                    ephemeral=excluded.ephemeral,payload_json=excluded.payload_json,
                    evidence_json=excluded.evidence_json,last_seen_at=excluded.last_seen_at""", row)
            connection.commit()
        return {"provider_id": snapshot.provider_id, "domain_id": snapshot.domain_id,
                "observed_nodes": len(snapshot.nodes),
                "observed_gpus": sum(node.gpu_count for node in snapshot.nodes)}

    def mark_provider_missing(self, provider_id: str, domain_id: str, *, observed_at: float | None = None) -> int:
        """Withdraw a disappeared provider from eligibility without deleting history."""
        when = time.time() if observed_at is None else observed_at
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE compute_resource_inventory SET state=?,last_seen_at=? "
                "WHERE provider_id=? AND domain_id=? AND state != ?",
                (ResourceState.DEGRADED.value, when, provider_id, domain_id, ResourceState.QUARANTINED.value),
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
