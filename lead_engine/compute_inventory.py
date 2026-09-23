"""Durable provider-neutral physical resource inventory.

This inventory records observed compute resources and their evidence. It is
deliberately separate from the authoritative Thorio work queue.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict
from typing import Any

from .compute_provider import ProviderResourceSnapshot
from .compute_fabric_telemetry import summarize_route_health
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
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_fabric_path_health (
                path_key TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                gpu_uuid TEXT NOT NULL,
                nic TEXT NOT NULL,
                rdma_device TEXT NOT NULL,
                rdma_port INTEGER NOT NULL,
                link_layer TEXT NOT NULL,
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                first_quarantined_at REAL NOT NULL,
                last_updated_at REAL NOT NULL,
                cleared_at REAL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_fabric_path_health_identity "
                "ON compute_fabric_path_health(node_id,gpu_uuid,rdma_device,rdma_port)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_fabric_route_observations (
                observation_id TEXT PRIMARY KEY,
                path_key TEXT NOT NULL,
                observed_at REAL NOT NULL,
                latency_ms REAL,
                success INTEGER NOT NULL,
                evidence_json TEXT NOT NULL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_fabric_route_observations_path "
                "ON compute_fabric_route_observations(path_key,observed_at)"
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
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_placements (
                placement_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                workload_signature_json TEXT NOT NULL,
                selected_gpu_ids_json TEXT NOT NULL,
                selected_node_ids_json TEXT NOT NULL,
                selected_resource_keys_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                decision_trace_json TEXT NOT NULL,
                placement_schema_version INTEGER NOT NULL,
                created_at REAL NOT NULL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_placements_created "
                "ON compute_placements(created_at,placement_id)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_physical_components (
                component_key TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                component_type TEXT NOT NULL,
                identity TEXT NOT NULL,
                parent_identity TEXT,
                pci_parent_identity TEXT,
                numa_identity TEXT,
                attributes_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                observed_at REAL NOT NULL,
                first_seen_at REAL NOT NULL,
                last_seen_at REAL NOT NULL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_physical_components_location "
                "ON compute_physical_components(provider_id,domain_id,node_id,component_type)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_physical_components_identity "
                "ON compute_physical_components(identity)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_physical_component_history (
                observation_id TEXT PRIMARY KEY,
                component_key TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                component_type TEXT NOT NULL,
                identity TEXT NOT NULL,
                parent_identity TEXT,
                pci_parent_identity TEXT,
                numa_identity TEXT,
                attributes_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                observed_at REAL NOT NULL,
                recorded_at REAL NOT NULL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_physical_component_history_component "
                "ON compute_physical_component_history(component_key,observed_at)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_physical_fabric_paths (
                path_id TEXT PRIMARY KEY,
                source_gpu TEXT NOT NULL,
                destination_gpu TEXT NOT NULL,
                segments_json TEXT NOT NULL,
                fabric_domains_json TEXT NOT NULL,
                state TEXT NOT NULL,
                measurement_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            path_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(compute_physical_fabric_paths)").fetchall()}
            if "measurement_json" not in path_columns:
                connection.execute("ALTER TABLE compute_physical_fabric_paths ADD COLUMN measurement_json TEXT NOT NULL DEFAULT '{}'")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_physical_fabric_paths_endpoints "
                "ON compute_physical_fabric_paths(source_gpu,destination_gpu,state)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_physical_fabric_verifications (
                verification_id TEXT PRIMARY KEY,
                path_id TEXT NOT NULL,
                state TEXT NOT NULL,
                reason TEXT,
                failure_domain TEXT,
                evidence_json TEXT NOT NULL,
                observed_at REAL NOT NULL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_compute_physical_fabric_verifications_path "
                "ON compute_physical_fabric_verifications(path_id,observed_at)"
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
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(resource_key) DO UPDATE SET
                    provider_id=excluded.provider_id,domain_id=excluded.domain_id,
                    node_id=excluded.node_id,gpu_id=excluded.gpu_id,
                    identity_key=excluded.identity_key,
                    state=CASE WHEN compute_resource_inventory.state = 'reserved' THEN compute_resource_inventory.state ELSE excluded.state END,
                    observed_at=excluded.observed_at,expires_at=excluded.expires_at,
                    ephemeral=excluded.ephemeral,authentication_state=excluded.authentication_state,
                    payload_json=excluded.payload_json,
                    evidence_json=excluded.evidence_json,last_seen_at=excluded.last_seen_at""", row)
            connection.commit()
        physical_count = self._observe_physical_components(snapshot)
        return {"provider_id": snapshot.provider_id, "domain_id": snapshot.domain_id,
                "observed_nodes": len(snapshot.nodes),
                "observed_gpus": sum(node.gpu_count for node in snapshot.nodes),
                "observed_physical_components": physical_count}

    @staticmethod
    def _physical_component_records(snapshot: ProviderResourceSnapshot) -> tuple[dict[str, Any], ...]:
        evidence = snapshot.evidence if isinstance(snapshot.evidence, dict) else {}
        fabric = evidence.get("physical_fabric")
        if not isinstance(fabric, dict):
            return ()
        components = fabric.get("components")
        if not isinstance(components, list):
            return ()

        records: list[dict[str, Any]] = []
        for component in components:
            if not isinstance(component, dict):
                continue
            component_type = str(component.get("component_type") or "").strip()
            identity = str(component.get("identity") or "").strip()
            node_id = str(component.get("node_id") or "").strip()
            if not component_type or not identity or not node_id:
                continue
            attributes = component.get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
            records.append({
                "component_type": component_type,
                "identity": identity,
                "node_id": node_id,
                "parent_identity": component.get("parent_identity"),
                "pci_parent_identity": component.get("pci_parent_identity"),
                "numa_identity": component.get("numa_identity"),
                "attributes": dict(attributes),
                "evidence": dict(component.get("evidence") or {}) if isinstance(component.get("evidence"), dict) else {},
            })
        return tuple(records)

    def _observe_physical_components(self, snapshot: ProviderResourceSnapshot) -> int:
        records = self._physical_component_records(snapshot)
        if not records:
            return 0
        now = time.time()
        with self._connect() as connection:
            for record in records:
                key_material = {
                    "provider_id": snapshot.provider_id,
                    "domain_id": snapshot.domain_id,
                    "node_id": record["node_id"],
                    "component_type": record["component_type"],
                    "identity": record["identity"],
                }
                component_key = hashlib.sha256(
                    json.dumps(key_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                observation_material = {
                    "component_key": component_key,
                    "provider_id": snapshot.provider_id,
                    "domain_id": snapshot.domain_id,
                    "node_id": record["node_id"],
                    "component_type": record["component_type"],
                    "identity": record["identity"],
                    "observed_at": snapshot.observed_at,
                }
                observation_id = hashlib.sha256(
                    json.dumps(observation_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """INSERT OR IGNORE INTO compute_physical_component_history
                       (observation_id,component_key,provider_id,domain_id,node_id,component_type,identity,
                        parent_identity,pci_parent_identity,numa_identity,attributes_json,evidence_json,
                        observed_at,recorded_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        observation_id, component_key, snapshot.provider_id, snapshot.domain_id, record["node_id"],
                        record["component_type"], record["identity"], record["parent_identity"],
                        record["pci_parent_identity"], record["numa_identity"],
                        json.dumps(record["attributes"], ensure_ascii=False, sort_keys=True),
                        json.dumps(record["evidence"], ensure_ascii=False, sort_keys=True),
                        snapshot.observed_at, now,
                    ),
                )
                connection.execute(
                    """INSERT INTO compute_physical_components
                       (component_key,provider_id,domain_id,node_id,component_type,identity,
                        parent_identity,pci_parent_identity,numa_identity,attributes_json,evidence_json,
                        observed_at,first_seen_at,last_seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(component_key) DO UPDATE SET
                         parent_identity=excluded.parent_identity,
                         pci_parent_identity=excluded.pci_parent_identity,
                         numa_identity=excluded.numa_identity,
                         attributes_json=excluded.attributes_json,
                         evidence_json=excluded.evidence_json,
                         observed_at=excluded.observed_at,
                         last_seen_at=excluded.last_seen_at""",
                    (
                        component_key, snapshot.provider_id, snapshot.domain_id, record["node_id"],
                        record["component_type"], record["identity"], record["parent_identity"],
                        record["pci_parent_identity"], record["numa_identity"],
                        json.dumps(record["attributes"], ensure_ascii=False, sort_keys=True),
                        json.dumps(record["evidence"], ensure_ascii=False, sort_keys=True),
                        snapshot.observed_at, now, now,
                    ),
                )
            connection.commit()
        return len(records)

    def persist_physical_path(self, path: Any) -> None:
        """Persist the current concrete path state without replacing history."""
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO compute_physical_fabric_paths
                   (path_id,source_gpu,destination_gpu,segments_json,fabric_domains_json,state,measurement_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(path_id) DO UPDATE SET
                     segments_json=excluded.segments_json,
                     fabric_domains_json=excluded.fabric_domains_json,
                     state=excluded.state,
                     measurement_json=excluded.measurement_json,
                     updated_at=excluded.updated_at""",
                (
                    path.path_id, path.source_gpu, path.destination_gpu,
                    json.dumps(list(path.segments), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(path.fabric_domains), ensure_ascii=False, sort_keys=True),
                    path.state.value, json.dumps(dict(getattr(path, "measurement", {}) or {}), ensure_ascii=False, sort_keys=True), now, now,
                ),
            )
            connection.commit()

    def persist_physical_verification(
        self,
        verification: Any,
        *,
        evidence: dict[str, Any] | None = None,
        observed_at: float | None = None,
    ) -> None:
        """Append an immutable verification observation for one exact path."""
        timestamp = time.time() if observed_at is None else observed_at
        evidence_payload = dict(evidence or {})
        material = {
            "path_id": verification.path_id,
            "state": verification.state.value,
            "reason": verification.reason,
            "failure_domain": verification.failure_domain,
            "evidence": evidence_payload,
            "observed_at": timestamp,
        }
        verification_id = hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """UPDATE compute_physical_fabric_paths
                   SET state=?, measurement_json=?, updated_at=?
                   WHERE path_id=?""",
                (
                    verification.state.value,
                    json.dumps(dict(getattr(verification, "measurement", {}) or {}), ensure_ascii=False, sort_keys=True),
                    timestamp,
                    verification.path_id,
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO compute_physical_fabric_verifications
                   (verification_id,path_id,state,reason,failure_domain,evidence_json,observed_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    verification_id, verification.path_id, verification.state.value,
                    verification.reason, verification.failure_domain,
                    json.dumps(evidence_payload, ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
            connection.commit()

    def fail_physical_path(
        self,
        path_id: str,
        *,
        reason: str,
        evidence: dict[str, Any] | None = None,
        observed_at: float | None = None,
    ) -> bool:
        """Move one exact concrete path to FAILED and retain immutable evidence."""
        timestamp = time.time() if observed_at is None else observed_at
        with self._connect() as connection:
            row = connection.execute(
                "SELECT source_gpu,destination_gpu FROM compute_physical_fabric_paths WHERE path_id=?",
                (str(path_id),),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE compute_physical_fabric_paths SET state='FAILED',updated_at=? WHERE path_id=?",
                (timestamp, str(path_id)),
            )
            connection.commit()
        verification_id = hashlib.sha256(
            json.dumps(
                {
                    "path_id": str(path_id),
                    "state": "FAILED",
                    "reason": str(reason),
                    "evidence": dict(evidence or {}),
                    "observed_at": timestamp,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO compute_physical_fabric_verifications
                   (verification_id,path_id,state,reason,failure_domain,evidence_json,observed_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    verification_id,
                    str(path_id),
                    "FAILED",
                    str(reason),
                    str((evidence or {}).get("failure_domain") or "unresolved"),
                    json.dumps(dict(evidence or {}), ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
            connection.commit()
        return True

    def verified_physical_paths(
        self,
        *,
        source_gpu: str | None = None,
        destination_gpu: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return only concrete paths whose current state is VERIFIED or stronger."""
        clauses = ["state IN (?,?,?)"]
        params: list[Any] = ["VERIFIED", "MEASURED", "REVERIFIED"]
        if source_gpu is not None:
            clauses.append("source_gpu=?")
            params.append(str(source_gpu))
        if destination_gpu is not None:
            clauses.append("destination_gpu=?")
            params.append(str(destination_gpu))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT path_id,source_gpu,destination_gpu,segments_json,fabric_domains_json,state,"
                "measurement_json,created_at,updated_at FROM compute_physical_fabric_paths WHERE "
                + " AND ".join(clauses)
                + " ORDER BY path_id",
                tuple(params),
            ).fetchall()
        return [
            {
                "path_id": row["path_id"],
                "source_gpu": row["source_gpu"],
                "destination_gpu": row["destination_gpu"],
                "segments": json.loads(row["segments_json"]),
                "fabric_domains": json.loads(row["fabric_domains_json"]),
                "state": row["state"],
                "measurement": json.loads(row["measurement_json"] or "{}") if "measurement_json" in row.keys() else {},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def physical_paths(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT path_id,source_gpu,destination_gpu,segments_json,fabric_domains_json,
                          state,measurement_json,created_at,updated_at
                   FROM compute_physical_fabric_paths
                   ORDER BY created_at,path_id"""
            ).fetchall()
        return [
            {
                "path_id": row["path_id"],
                "source_gpu": row["source_gpu"],
                "destination_gpu": row["destination_gpu"],
                "segments": json.loads(row["segments_json"]),
                "fabric_domains": json.loads(row["fabric_domains_json"]),
                "state": row["state"],
                "measurement": json.loads(row["measurement_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def physical_verification_history(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT verification_id,path_id,state,reason,failure_domain,evidence_json,observed_at
                   FROM compute_physical_fabric_verifications
                   ORDER BY observed_at,verification_id"""
            ).fetchall()
        return [
            {
                "verification_id": row["verification_id"],
                "path_id": row["path_id"],
                "state": row["state"],
                "reason": row["reason"],
                "failure_domain": row["failure_domain"],
                "evidence": json.loads(row["evidence_json"]),
                "observed_at": row["observed_at"],
            }
            for row in rows
        ]

    def physical_component_observations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT component_key,provider_id,domain_id,node_id,component_type,identity,
                          parent_identity,pci_parent_identity,numa_identity,attributes_json,
                          evidence_json,observed_at,first_seen_at,last_seen_at
                   FROM compute_physical_components
                   ORDER BY provider_id,domain_id,node_id,component_type,identity"""
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["attributes"] = json.loads(item.pop("attributes_json") or "{}")
            item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            result.append(item)
        return result

    def physical_component_history(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT observation_id,component_key,provider_id,domain_id,node_id,component_type,identity,
                          parent_identity,pci_parent_identity,numa_identity,attributes_json,evidence_json,
                          observed_at,recorded_at
                   FROM compute_physical_component_history
                   ORDER BY observed_at,observation_id"""
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["attributes"] = json.loads(item.pop("attributes_json") or "{}")
            item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            result.append(item)
        return result

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
                "WHERE state IN (?,?) AND authentication_state = ? "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY provider_id,domain_id,node_id,resource_type,resource_key",
                (ResourceState.HEALTHY.value, ResourceState.AVAILABLE.value, "authenticated", current),
            ).fetchall()
        result = [dict(row) for row in rows]
        quarantined = self.quarantined_fabric_paths()
        by_gpu: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for path in quarantined:
            by_gpu.setdefault((str(path["node_id"]), str(path["gpu_uuid"])), []).append({
                "path_key": path["path_key"],
                "nic": path["nic"],
                "rdma_device": path["rdma_device"],
                "rdma_port": int(path["rdma_port"]),
                "link_layer": path["link_layer"],
                "reason": path["reason"],
            })
        for row in result:
            if row["resource_type"] == "gpu":
                payload = json.loads(row["payload_json"])
                row["quarantined_fabric_paths"] = by_gpu.get(
                    (str(row["node_id"]), str(payload.get("gpu_uuid") or "")), []
                )
        return result

    @staticmethod
    def fabric_path_key(path: dict[str, Any]) -> str:
        required = ("node_id", "gpu_uuid", "nic", "rdma_device", "rdma_port", "link_layer")
        values = {name: path.get(name) for name in required}
        if any(values[name] in (None, "") for name in required):
            raise ValueError("fabric path identity is incomplete")
        if not isinstance(values["rdma_port"], int) or values["rdma_port"] < 1:
            raise ValueError("fabric path rdma_port must be a positive integer")
        canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def quarantine_fabric_path(self, path: dict[str, Any], *, reason: str, evidence: dict[str, Any] | None = None) -> str:
        path_key = self.fabric_path_key(path)
        now = time.time()
        identity = {name: path[name] for name in ("node_id", "gpu_uuid", "nic", "rdma_device", "rdma_port", "link_layer")}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO compute_fabric_path_health
                   (path_key,node_id,gpu_uuid,nic,rdma_device,rdma_port,link_layer,state,reason,evidence_json,first_quarantined_at,last_updated_at,cleared_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                   ON CONFLICT(path_key) DO UPDATE SET
                     state='quarantined',reason=excluded.reason,evidence_json=excluded.evidence_json,
                     last_updated_at=excluded.last_updated_at,cleared_at=NULL""",
                (
                    path_key, identity["node_id"], identity["gpu_uuid"], identity["nic"],
                    identity["rdma_device"], identity["rdma_port"], identity["link_layer"],
                    ResourceState.QUARANTINED.value, str(reason)[:4000],
                    json.dumps(dict(evidence or {}), ensure_ascii=False, sort_keys=True), now, now,
                ),
            )
            connection.commit()
        return path_key

    def quarantined_fabric_paths(self, *, node_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM compute_fabric_path_health WHERE state=?"
        args: list[Any] = [ResourceState.QUARANTINED.value]
        if node_id is not None:
            query += " AND node_id=?"
            args.append(node_id)
        query += " ORDER BY node_id,gpu_uuid,nic,rdma_device,rdma_port"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, tuple(args)).fetchall()]

    def is_fabric_path_quarantined(self, path: dict[str, Any]) -> bool:
        path_key = self.fabric_path_key(path)
        with self._connect() as connection:
            row = connection.execute("SELECT state FROM compute_fabric_path_health WHERE path_key=?", (path_key,)).fetchone()
        return bool(row and row["state"] == ResourceState.QUARANTINED.value)

    def revalidate_fabric_path(self, path: dict[str, Any], *, verification: dict[str, Any]) -> bool:
        """Clear a path quarantine only after a newer authenticated physical observation verifies it."""
        if verification.get("verified") is not True:
            raise ValueError("path quarantine can only be cleared by verified evidence")
        for field in ("node_id", "gpu_uuid", "nic", "rdma_device", "rdma_port", "link_layer"):
            if verification.get(field) != path.get(field):
                raise ValueError(f"path revalidation evidence does not match {field}")
        path_key = self.fabric_path_key(path)
        now = time.time()
        with self._connect() as connection:
            quarantine = connection.execute(
                "SELECT last_updated_at FROM compute_fabric_path_health WHERE path_key=? AND state=?",
                (path_key, ResourceState.QUARANTINED.value),
            ).fetchone()
            if quarantine is None:
                return False
            resource = connection.execute(
                """SELECT * FROM compute_resource_inventory
                   WHERE node_id=? AND identity_key=? AND resource_type='gpu'
                   ORDER BY last_seen_at DESC LIMIT 1""",
                (str(path["node_id"]), str(path["gpu_uuid"])),
            ).fetchone()
            if resource is None:
                raise ValueError("path revalidation has no current inventory record for the GPU")
            if resource["authentication_state"] != "authenticated":
                raise ValueError("path revalidation requires authenticated inventory evidence")
            if resource["expires_at"] is not None and float(resource["expires_at"]) <= now:
                raise ValueError("path revalidation evidence has expired")
            if float(resource["observed_at"]) <= float(quarantine["last_updated_at"]):
                raise ValueError("path revalidation requires a newer physical observation than the quarantine")
            evidence = json.loads(resource["evidence_json"] or "{}")
            network = evidence.get("network")
            locality = network.get("gpu_nic_locality") if isinstance(network, dict) else None
            rdma = network.get("rdma") if isinstance(network, dict) else None
            if not isinstance(locality, list) or not isinstance(rdma, dict) or not isinstance(rdma.get("links"), list):
                raise ValueError("path revalidation lacks complete physical network evidence")
            locality_matches = [
                item for item in locality
                if isinstance(item, dict)
                and str(item.get("gpu_uuid") or "").strip() == str(path["gpu_uuid"]).strip()
                and str(item.get("nic") or "").strip() == str(path["nic"]).strip()
                and str(item.get("rdma_device") or "").strip() == str(path["rdma_device"]).strip()
                and item.get("rdma_port") == path["rdma_port"]
                and str(item.get("link_layer") or "").strip() == str(path["link_layer"]).strip()
            ]
            if not locality_matches:
                raise ValueError("path revalidation physical GPU-to-NIC locality does not match the quarantined path")
            active_links = [
                link for link in rdma["links"]
                if isinstance(link, dict)
                and str(link.get("rdma_device") or "").strip() == str(path["rdma_device"]).strip()
                and link.get("port") == path["rdma_port"]
                and str(link.get("link_layer") or "").strip() == str(path["link_layer"]).strip()
                and str(link.get("state") or "").strip().upper() == "ACTIVE"
                and str(link.get("physical_state") or "").strip().upper() in {"LINK_UP", "LINK_ACTIVE"}
            ]
            if not active_links:
                raise ValueError("path revalidation requires an active physical RDMA link")
            cursor = connection.execute(
                "UPDATE compute_fabric_path_health SET state=?,last_updated_at=?,cleared_at=? WHERE path_key=? AND state=?",
                (ResourceState.AVAILABLE.value, now, now, path_key, ResourceState.QUARANTINED.value),
            )
            connection.commit()
            return cursor.rowcount == 1


    def record_fabric_route_observation(
        self,
        path: dict[str, Any],
        *,
        latency_ms: float | None,
        success: bool,
        observed_at: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        """Persist one authoritative route observation idempotently."""
        path_key = self.fabric_path_key(path)
        if latency_ms is not None:
            latency_ms = float(latency_ms)
            if latency_ms <= 0:
                raise ValueError("latency_ms must be positive when provided")
        when = time.time() if observed_at is None else float(observed_at)
        payload = {
            "path_key": path_key,
            "observed_at": when,
            "latency_ms": latency_ms,
            "success": bool(success),
            "evidence": dict(evidence or {}),
        }
        observation_id = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO compute_fabric_route_observations
                   (observation_id,path_key,observed_at,latency_ms,success,evidence_json)
                   VALUES(?,?,?,?,?,?)""",
                (
                    observation_id, path_key, when, latency_ms, int(bool(success)),
                    json.dumps(dict(evidence or {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            connection.commit()
        return observation_id

    def fabric_route_health_index(self) -> dict[str, dict[str, Any]]:
        """Return observed route health/congestion evidence keyed by physical path."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT path_key,observed_at,latency_ms,success
                   FROM compute_fabric_route_observations
                   ORDER BY path_key,observed_at,observation_id"""
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["path_key"]), []).append({
                "observed_at": float(row["observed_at"]),
                "latency_ms": row["latency_ms"],
                "success": bool(row["success"]),
            })
        return {path_key: summarize_route_health(samples) for path_key, samples in grouped.items()}

    @staticmethod
    def _placement_record(placement: Any) -> dict[str, Any]:
        required = (
            "placement_id",
            "provider_id",
            "domain_id",
            "workload_signature",
            "selected_gpu_ids",
            "selected_node_ids",
            "selected_resource_keys",
            "evidence",
            "decision_trace",
        )
        if any(not hasattr(placement, field) for field in required):
            raise ValueError("placement is missing required durable fields")
        placement_id = str(placement.placement_id).strip()
        if not placement_id:
            raise ValueError("placement_id is required")
        return {
            "placement_id": placement_id,
            "provider_id": str(placement.provider_id),
            "domain_id": str(placement.domain_id),
            "workload_signature": list(placement.workload_signature),
            "selected_gpu_ids": list(placement.selected_gpu_ids),
            "selected_node_ids": list(placement.selected_node_ids),
            "selected_resource_keys": list(placement.selected_resource_keys),
            "evidence": dict(placement.evidence),
            "decision_trace": [dict(item) for item in placement.decision_trace],
        }

    def persist_placement(self, placement: Any) -> dict[str, Any]:
        record = self._placement_record(placement)
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO compute_placements
                   (placement_id,provider_id,domain_id,workload_signature_json,
                    selected_gpu_ids_json,selected_node_ids_json,selected_resource_keys_json,
                    evidence_json,decision_trace_json,placement_schema_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["placement_id"],
                    record["provider_id"],
                    record["domain_id"],
                    json.dumps(record["workload_signature"], ensure_ascii=False, sort_keys=True),
                    json.dumps(record["selected_gpu_ids"], ensure_ascii=False, sort_keys=True),
                    json.dumps(record["selected_node_ids"], ensure_ascii=False, sort_keys=True),
                    json.dumps(record["selected_resource_keys"], ensure_ascii=False, sort_keys=True),
                    json.dumps(record["evidence"], ensure_ascii=False, sort_keys=True),
                    json.dumps(record["decision_trace"], ensure_ascii=False, sort_keys=True),
                    1,
                    now,
                ),
            )
            connection.commit()
        return self.placement(record["placement_id"])

    def placement(self, placement_id: str) -> dict[str, Any] | None:
        key = str(placement_id).strip()
        if not key:
            raise ValueError("placement_id is required")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_placements WHERE placement_id=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "placement_id": str(row["placement_id"]),
            "provider_id": str(row["provider_id"]),
            "domain_id": str(row["domain_id"]),
            "workload_signature": json.loads(row["workload_signature_json"]),
            "selected_gpu_ids": json.loads(row["selected_gpu_ids_json"]),
            "selected_node_ids": json.loads(row["selected_node_ids_json"]),
            "selected_resource_keys": json.loads(row["selected_resource_keys_json"]),
            "evidence": json.loads(row["evidence_json"]),
            "decision_trace": json.loads(row["decision_trace_json"]),
            "placement_schema_version": int(row["placement_schema_version"]),
            "created_at": float(row["created_at"]),
        }

    def placements(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT placement_id FROM compute_placements ORDER BY created_at,placement_id"
            ).fetchall()
        return [self.placement(str(row["placement_id"])) for row in rows]

    def get(self, resource_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_resource_inventory WHERE resource_key=?", (resource_key,)
            ).fetchone()
        return dict(row) if row else None

    def quarantine_resource(
        self,
        resource_key: str,
        *,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        """Quarantine one physical resource and durably retain the failure evidence."""
        key = str(resource_key).strip()
        detail = str(reason).strip()
        if not key or not detail:
            raise ValueError("resource_key and reason are required")
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT evidence_json,state FROM compute_resource_inventory WHERE resource_key=?",
                (key,),
            ).fetchone()
            if not row:
                return False
            current = json.loads(row["evidence_json"] or "{}")
            if not isinstance(current, dict):
                current = {}
            quarantine = {
                "reason": detail[:4000],
                "recorded_at": now,
            }
            if evidence is not None:
                if not isinstance(evidence, dict):
                    raise ValueError("quarantine evidence must be an object")
                quarantine["evidence"] = evidence
            current["quarantine"] = quarantine
            connection.execute(
                "UPDATE compute_resource_inventory SET state=?,evidence_json=?,last_seen_at=? "
                "WHERE resource_key=? AND state NOT IN (?,?)",
                (
                    ResourceState.QUARANTINED.value,
                    json.dumps(current, ensure_ascii=False, sort_keys=True),
                    now,
                    key,
                    ResourceState.RELEASED.value,
                    ResourceState.QUARANTINED.value,
                ),
            )
            changed = connection.total_changes > 0
            connection.commit()
        return changed

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

    def reserve_allocation(
        self,
        allocation_id: str,
        provider_id: str,
        domain_id: str,
        resource_keys: list[str] | tuple[str, ...],
    ) -> None:
        """Atomically reserve resources and create their durable ownership record."""
        keys = tuple(dict.fromkeys(str(key) for key in resource_keys))
        if not allocation_id.strip() or not provider_id.strip() or not domain_id.strip() or not keys:
            raise ValueError("allocation identity and resources are required")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT provider_id,domain_id,resource_keys_json,state FROM compute_allocations WHERE allocation_id=?",
                (allocation_id,),
            ).fetchone()
            if existing:
                same = (
                    existing["provider_id"] == provider_id
                    and existing["domain_id"] == domain_id
                    and tuple(json.loads(existing["resource_keys_json"])) == keys
                )
                connection.rollback()
                if not same:
                    raise ValueError("allocation_id already exists with different resources")
                return
            rows = connection.execute(
                f"SELECT resource_key,state,provider_id,domain_id,authentication_state,expires_at "
                f"FROM compute_resource_inventory "
                f"WHERE resource_key IN ({','.join('?' for _ in keys)})", keys
            ).fetchall()
            by_key = {row["resource_key"]: row for row in rows}
            if len(by_key) != len(keys) or any(
                row["state"] not in {ResourceState.HEALTHY.value, ResourceState.AVAILABLE.value}
                or row["provider_id"] != provider_id
                or row["domain_id"] != domain_id
                or row["authentication_state"] != "authenticated"
                or (row["expires_at"] is not None and float(row["expires_at"]) <= now)
                for row in by_key.values()
            ):
                connection.rollback()
                raise ValueError("allocation resources are no longer available")
            connection.executemany(
                "UPDATE compute_resource_inventory SET state=?,last_seen_at=? WHERE resource_key=?",
                [(ResourceState.RESERVED.value, now, key) for key in keys],
            )
            connection.execute(
                """INSERT INTO compute_allocations
                   (allocation_id,state,provider_id,domain_id,resource_keys_json,created_at,updated_at)
                   VALUES (?, 'reserved', ?, ?, ?, ?, ?)""",
                (allocation_id, provider_id, domain_id, json.dumps(keys, ensure_ascii=False), now, now),
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
