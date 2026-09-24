"""Free compute inventory, worker registration, and lease coordination.

Provider-neutral and free-only. Workers use the existing SQLite database, so
work state survives process restarts. Credentials are never handled here.
"""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import sqlite3
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Mapping, Optional

from .compute_resources import GpuResource


@dataclass(frozen=True)
class ComputeCapacity:
    node_id: str
    cpu_count: int
    memory_mb: int
    architecture: str
    persistent: bool = False

    @property
    def recommended_workers(self) -> int:
        if self.cpu_count <= 0 or self.memory_mb <= 0:
            return 1
        return max(1, min(max(1, self.cpu_count - 1), max(1, self.memory_mb // 2048)))

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["recommended_workers"] = self.recommended_workers
        return result


def _memory_mb() -> int:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if match:
            return max(1, int(match.group(1)) // 1024)
    return max(1, int(os.environ.get("THORIO_COMPUTE_MEMORY_MB", "2048")))


def local_capacity(*, node_id: str | None = None, persistent: bool = False) -> ComputeCapacity:
    resolved_id = (node_id or os.environ.get("THORIO_NODE_ID") or platform.node() or "local").strip() or "local"
    return ComputeCapacity(resolved_id, os.cpu_count() or 1, _memory_mb(), platform.machine() or "unknown", persistent)


def worker_budget(capacity: ComputeCapacity, *, requested: int | None = None) -> int:
    if not isinstance(capacity, ComputeCapacity):
        raise ValueError("capacity must be a ComputeCapacity instance")
    if requested is not None and (isinstance(requested, bool) or requested <= 0):
        raise ValueError("requested worker count must be positive")
    configured = int(os.environ.get("THORIO_MAX_LOCAL_WORKERS", "0"))
    if configured < 0:
        raise ValueError("THORIO_MAX_LOCAL_WORKERS must not be negative")
    limit = capacity.recommended_workers
    if configured:
        limit = min(limit, configured)
    if requested is not None:
        limit = min(limit, requested)
    return max(1, limit)


def pool_snapshot(capacities: Mapping[str, ComputeCapacity]) -> Dict[str, Any]:
    if not isinstance(capacities, Mapping) or any(not isinstance(v, ComputeCapacity) for v in capacities.values()):
        raise ValueError("capacities must map node IDs to ComputeCapacity instances")
    nodes = {str(k): v.to_dict() for k, v in capacities.items()}
    return {"free_only": True, "node_count": len(nodes),
            "total_cpu": sum(v["cpu_count"] for v in nodes.values()),
            "total_memory_mb": sum(v["memory_mb"] for v in nodes.values()),
            "total_recommended_workers": sum(v["recommended_workers"] for v in nodes.values()),
            "nodes": nodes}


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    hostname: str
    architecture: str
    cpu_count: int
    memory_mb: int
    capabilities: tuple[str, ...] = ("lead-processing",)
    gpu_resources: tuple[GpuResource, ...] = ()
    driver_version: str | None = None
    cuda_version: str | None = None
    nccl_version: str | None = None
    nic_names: tuple[str, ...] = ()
    gpu_discovery_state: str = "not_probed"
    gpu_discovery_error: str = ""
    domain_id: str = ""
    physical_fabric_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cpu_count < 1 or self.memory_mb < 1:
            raise ValueError("worker resources must be positive")
        if any(gpu.node_id != self.worker_id for gpu in self.gpu_resources):
            raise ValueError("worker GPU resources must belong to worker_id")
        if len({gpu.identity_key for gpu in self.gpu_resources}) != len(self.gpu_resources):
            raise ValueError("worker GPU identities must be unique")
        if self.gpu_discovery_state not in {"not_probed", "healthy", "no_gpu", "degraded"}:
            raise ValueError("unsupported gpu_discovery_state")
        domain_id = self.domain_id.strip() or self.worker_id
        if not isinstance(self.physical_fabric_evidence, Mapping):
            raise ValueError("physical_fabric_evidence must be a mapping")
        object.__setattr__(self, "domain_id", domain_id)
        object.__setattr__(self, "physical_fabric_evidence", dict(self.physical_fabric_evidence))


def local_worker_identity(worker_id: Optional[str] = None) -> WorkerIdentity:
    capacity = local_capacity(node_id=worker_id)
    gpu_resources: tuple[GpuResource, ...] = ()
    driver_version = cuda_version = nccl_version = None
    gpu_state = "not_probed"
    gpu_error = ""
    nic_names: tuple[str, ...] = ()
    physical_fabric_evidence: Mapping[str, Any] = {}
    domain_id = (os.environ.get("THORIO_COMPUTE_DOMAIN") or capacity.node_id).strip() or capacity.node_id
    try:
        from .nvidia_provider import NvidiaDiscoveryError, NvidiaProvider
        snapshot = NvidiaProvider(node_id=capacity.node_id).discover()
        node = snapshot.nodes[0]
        gpu_resources = node.gpus
        driver_version = node.driver_version
        cuda_version = node.cuda_version
        gpu_state = "healthy" if gpu_resources else "no_gpu"
        nic_names = node.nic_names
        physical_fabric_evidence = dict(getattr(snapshot, "evidence", None) or {})
    except NvidiaDiscoveryError as exc:
        gpu_state = "degraded"
        gpu_error = str(exc)[:2000]

    return WorkerIdentity(
        capacity.node_id, socket.gethostname(), capacity.architecture,
        capacity.cpu_count, capacity.memory_mb, ("lead-processing",),
        gpu_resources, driver_version, cuda_version, nccl_version, tuple(sorted(nic_names)), gpu_state, gpu_error,
        domain_id, physical_fabric_evidence,
    )


class ComputePool:
    """SQLite-backed provider-neutral registry and exclusive task lease pool."""

    LOGICAL_SLOTS_PER_WORKER = 1

    def __init__(self, db_path: str = "data/lead_engine.db", lease_seconds: int = 300):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.db_path = db_path
        self.lease_seconds = lease_seconds
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_workers (
                worker_id TEXT PRIMARY KEY, hostname TEXT NOT NULL, architecture TEXT NOT NULL,
                cpu_count INTEGER NOT NULL, memory_mb INTEGER NOT NULL, capabilities_json TEXT NOT NULL,
                gpu_resources_json TEXT NOT NULL DEFAULT '[]', driver_version TEXT, cuda_version TEXT,
                nccl_version TEXT, nic_names_json TEXT NOT NULL DEFAULT '[]',
                gpu_discovery_state TEXT NOT NULL DEFAULT 'not_probed', gpu_discovery_error TEXT NOT NULL DEFAULT '',
                domain_id TEXT NOT NULL DEFAULT '', physical_fabric_evidence_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'ready', last_heartbeat REAL NOT NULL,
                current_load INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL)""")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(compute_workers)").fetchall()}
            if "status_reason" not in columns:
                connection.execute("ALTER TABLE compute_workers ADD COLUMN status_reason TEXT NOT NULL DEFAULT ''")
            migrations = {
                "gpu_resources_json": "ALTER TABLE compute_workers ADD COLUMN gpu_resources_json TEXT NOT NULL DEFAULT '[]'",
                "driver_version": "ALTER TABLE compute_workers ADD COLUMN driver_version TEXT",
                "cuda_version": "ALTER TABLE compute_workers ADD COLUMN cuda_version TEXT",
                "nccl_version": "ALTER TABLE compute_workers ADD COLUMN nccl_version TEXT",
                "nic_names_json": "ALTER TABLE compute_workers ADD COLUMN nic_names_json TEXT NOT NULL DEFAULT '[]'",
                "gpu_discovery_state": "ALTER TABLE compute_workers ADD COLUMN gpu_discovery_state TEXT NOT NULL DEFAULT 'not_probed'",
                "gpu_discovery_error": "ALTER TABLE compute_workers ADD COLUMN gpu_discovery_error TEXT NOT NULL DEFAULT ''",
                "domain_id": "ALTER TABLE compute_workers ADD COLUMN domain_id TEXT NOT NULL DEFAULT ''",
                "physical_fabric_evidence_json": "ALTER TABLE compute_workers ADD COLUMN physical_fabric_evidence_json TEXT NOT NULL DEFAULT '{}'",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute("""CREATE TABLE IF NOT EXISTS work_leases (
                lead_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, lease_token TEXT NOT NULL UNIQUE,
                claimed_at REAL NOT NULL, lease_until REAL NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_workers_heartbeat ON compute_workers(last_heartbeat)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_work_leases_worker ON work_leases(worker_id)")
            connection.commit()

    @staticmethod
    def _gpu_json(gpus: tuple[GpuResource, ...]) -> str:
        return json.dumps([{**asdict(gpu), "health_state": gpu.health_state.value, "availability_state": gpu.availability_state.value} for gpu in gpus], ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _gpu_resources(value: str) -> tuple[GpuResource, ...]:
        raw = json.loads(value or "[]")
        if not isinstance(raw, list):
            raise ValueError("gpu_resources_json must contain a list")
        from .compute_resources import ResourceState
        result = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("GPU resource payload must contain objects")
            result.append(GpuResource(
                node_id=str(item["node_id"]), gpu_id=str(item["gpu_id"]), gpu_uuid=item.get("gpu_uuid"), model=item.get("model"),
                vram_bytes=item.get("vram_bytes"), compute_capability=item.get("compute_capability"), driver_version=item.get("driver_version"),
                cuda_version=item.get("cuda_version"), pci_bus_id=item.get("pci_bus_id"), numa_node=item.get("numa_node"),
                nvlink_domain=item.get("nvlink_domain"), topology_domain=item.get("topology_domain"),
                health_state=ResourceState(str(item.get("health_state", ResourceState.DISCOVERED.value))),
                availability_state=ResourceState(str(item.get("availability_state", ResourceState.DISCOVERED.value))),
            ))
        return tuple(result)

    def register(self, identity: WorkerIdentity) -> Dict[str, Any]:
        if identity.cpu_count < 1 or identity.memory_mb < 1:
            raise ValueError("worker resources must be positive")
        now = time.time()
        with self._connect() as connection:
            connection.execute("""INSERT INTO compute_workers
                (worker_id,hostname,architecture,cpu_count,memory_mb,capabilities_json,
                 gpu_resources_json,driver_version,cuda_version,nccl_version,nic_names_json,
                 gpu_discovery_state,gpu_discovery_error,domain_id,physical_fabric_evidence_json,status,last_heartbeat,current_load,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready',?,0,?)
                ON CONFLICT(worker_id) DO UPDATE SET hostname=excluded.hostname,
                architecture=excluded.architecture,cpu_count=excluded.cpu_count,memory_mb=excluded.memory_mb,
                capabilities_json=excluded.capabilities_json,gpu_resources_json=excluded.gpu_resources_json,
                driver_version=excluded.driver_version,cuda_version=excluded.cuda_version,
                nccl_version=excluded.nccl_version,nic_names_json=excluded.nic_names_json,
                gpu_discovery_state=excluded.gpu_discovery_state,gpu_discovery_error=excluded.gpu_discovery_error,
                domain_id=excluded.domain_id,physical_fabric_evidence_json=excluded.physical_fabric_evidence_json,
                status=CASE WHEN compute_workers.status IN ('quarantined','revoked') THEN compute_workers.status ELSE 'ready' END,
                last_heartbeat=excluded.last_heartbeat,updated_at=excluded.updated_at""",
                (identity.worker_id, identity.hostname, identity.architecture, identity.cpu_count, identity.memory_mb,
                 json.dumps(identity.capabilities), self._gpu_json(identity.gpu_resources), identity.driver_version,
                 identity.cuda_version, identity.nccl_version, json.dumps(identity.nic_names), identity.gpu_discovery_state,
                 identity.gpu_discovery_error, identity.domain_id,
                 json.dumps(identity.physical_fabric_evidence, ensure_ascii=False, sort_keys=True), now, now))
            connection.commit()
        return self.worker(identity.worker_id) or {}

    def heartbeat(self, worker_id: str, current_load: Optional[int] = None) -> bool:
        if current_load is not None and (isinstance(current_load, bool) or current_load < 0 or current_load > self.LOGICAL_SLOTS_PER_WORKER):
            raise ValueError("current_load must be between 0 and the worker's logical slot capacity")
        now = time.time()
        with self._connect() as connection:
            if current_load is None:
                cursor = connection.execute("UPDATE compute_workers SET last_heartbeat=?,updated_at=? WHERE worker_id=?", (now, now, worker_id))
            else:
                cursor = connection.execute("UPDATE compute_workers SET last_heartbeat=?,current_load=?,status=CASE WHEN status IN ('ready','stale') THEN 'ready' ELSE status END,updated_at=? WHERE worker_id=?", (now, current_load, now, worker_id))
            connection.commit()
            return cursor.rowcount == 1

    def reap_stale_workers(self, stale_after_seconds: Optional[int] = None) -> int:
        threshold = time.time() - (self.lease_seconds if stale_after_seconds is None else stale_after_seconds)
        with self._connect() as connection:
            cursor = connection.execute("UPDATE compute_workers SET status='stale',updated_at=? WHERE last_heartbeat < ? AND status != 'stale'", (time.time(), threshold))
            connection.commit()
            return cursor.rowcount

    def worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM compute_workers WHERE worker_id=?", (worker_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["capabilities"] = json.loads(item.pop("capabilities_json"))
        item["gpu_resources"] = self._gpu_resources(item.pop("gpu_resources_json", "[]"))
        item["nic_names"] = tuple(json.loads(item.pop("nic_names_json", "[]")))
        item["physical_fabric_evidence"] = json.loads(item.pop("physical_fabric_evidence_json", "{}") or "{}")
        item["domain_id"] = str(item.get("domain_id") or item["worker_id"])
        return item

    def workers(self, include_stale: bool = True) -> list[Dict[str, Any]]:
        if not include_stale:
            self.reap_stale_workers()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM compute_workers ORDER BY worker_id").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item.pop("capabilities_json"))
            item["gpu_resources"] = self._gpu_resources(item.pop("gpu_resources_json", "[]"))
            item["nic_names"] = tuple(json.loads(item.pop("nic_names_json", "[]")))
            item["physical_fabric_evidence"] = json.loads(item.pop("physical_fabric_evidence_json", "{}") or "{}")
            item["domain_id"] = str(item.get("domain_id") or item["worker_id"])
            result.append(item)
        return result

    def set_worker_status(self, worker_id: str, status: str, reason: str = "") -> bool:
        """Durably drain, quarantine, revoke, or readmit one worker."""
        allowed = {"ready", "draining", "quarantined", "revoked"}
        normalized = str(status).strip().lower()
        if normalized not in allowed:
            raise ValueError(f"unsupported worker status: {status}")
        with self._connect() as connection:
            cursor = connection.execute("UPDATE compute_workers SET status=?,status_reason=?,updated_at=? WHERE worker_id=?", (normalized, str(reason)[:4000], time.time(), worker_id))
            connection.commit()
            return cursor.rowcount == 1

    def drain_worker(self, worker_id: str, reason: str = "") -> bool:
        return self.set_worker_status(worker_id, "draining", reason)

    def quarantine_worker(self, worker_id: str, reason: str = "") -> bool:
        return self.set_worker_status(worker_id, "quarantined", reason)

    def revoke_worker(self, worker_id: str, reason: str = "") -> bool:
        return self.set_worker_status(worker_id, "revoked", reason)

    def readmit_worker(self, worker_id: str, reason: str = "") -> bool:
        """Readmit only after fresh heartbeat and physical GPU evidence are present."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status,last_heartbeat,gpu_discovery_state,physical_fabric_evidence_json "
                "FROM compute_workers WHERE worker_id=?",
                (worker_id,),
            ).fetchone()
        if not row:
            return False
        evidence = json.loads(row["physical_fabric_evidence_json"] or "{}")
        if row["gpu_discovery_state"] not in {"healthy", "degraded", "no_gpu"} or not isinstance(evidence, dict) or not evidence:
            return False
        if float(row["last_heartbeat"] or 0) <= 0:
            return False
        return self.set_worker_status(worker_id, "ready", reason)

    def reserve_task_slot(self, worker_id: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("UPDATE compute_workers SET current_load=current_load+1,updated_at=? WHERE worker_id=? AND status='ready' AND current_load < ?", (now, worker_id, self.LOGICAL_SLOTS_PER_WORKER))
            if cursor.rowcount != 1:
                connection.rollback(); return False
            connection.commit(); return True

    def release_task_slot(self, worker_id: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute("UPDATE compute_workers SET current_load=MAX(0,current_load-1),updated_at=? WHERE worker_id=?", (now, worker_id))
            connection.commit(); return cursor.rowcount == 1

    def claim(self, lead_id: str | int, worker_id: str) -> Optional[str]:
        lead_key = str(lead_id); now = time.time(); token = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            worker = connection.execute("SELECT status,current_load FROM compute_workers WHERE worker_id=?", (worker_id,)).fetchone()
            if not worker or worker["status"] != "ready" or worker["current_load"] >= self.LOGICAL_SLOTS_PER_WORKER:
                connection.rollback(); return None
            existing = connection.execute("SELECT lease_until FROM work_leases WHERE lead_id=?", (lead_key,)).fetchone()
            if existing and existing["lease_until"] > now:
                connection.rollback(); return None
            connection.execute("DELETE FROM work_leases WHERE lead_id=?", (lead_key,))
            connection.execute("INSERT INTO work_leases VALUES (?,?,?,?,?)", (lead_key, worker_id, token, now, now + self.lease_seconds))
            connection.execute("UPDATE compute_workers SET current_load=current_load+1,updated_at=? WHERE worker_id=?", (now, worker_id)); connection.commit()
        return token

    def complete(self, lead_id: str | int, worker_id: str, lease_token: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM work_leases WHERE lead_id=? AND worker_id=? AND lease_token=?", (str(lead_id), worker_id, lease_token))
            if cursor.rowcount != 1:
                connection.rollback(); return False
            connection.execute("UPDATE compute_workers SET current_load=MAX(0,current_load-1),updated_at=? WHERE worker_id=?", (now, worker_id)); connection.commit(); return True

    def release_expired(self) -> int:
        now = time.time()
        with self._connect() as connection:
            rows = connection.execute("SELECT worker_id FROM work_leases WHERE lease_until <= ?", (now,)).fetchall()
            connection.execute("DELETE FROM work_leases WHERE lease_until <= ?", (now,))
            for row in rows:
                connection.execute("UPDATE compute_workers SET current_load=MAX(0,current_load-1),updated_at=? WHERE worker_id=?", (now, row["worker_id"]))
            connection.commit(); return len(rows)

    def capacity_snapshot(self) -> Dict[str, Any]:
        self.reap_stale_workers()
        with self._connect() as connection:
            rows = connection.execute("""SELECT worker_id,hostname,architecture,cpu_count,memory_mb,status,current_load,last_heartbeat,capabilities_json,gpu_resources_json,gpu_discovery_state,gpu_discovery_error,domain_id
                FROM compute_workers ORDER BY worker_id""").fetchall()
        worker_items = []
        for row in rows:
            status = row["status"]; active = int(row["current_load"]); logical_slots = self.LOGICAL_SLOTS_PER_WORKER if status == "ready" else 0; gpus = self._gpu_resources(row["gpu_resources_json"])
            worker_items.append({"worker_id": row["worker_id"], "domain_id": str(row["domain_id"] or row["worker_id"]), "hostname": row["hostname"], "architecture": row["architecture"], "cpu_count": int(row["cpu_count"]), "memory_mb": int(row["memory_mb"]), "status": status, "capabilities": json.loads(row["capabilities_json"]), "gpu_count": len(gpus), "gpu_discovery_state": row["gpu_discovery_state"], "gpu_discovery_error": row["gpu_discovery_error"], "logical_slots": logical_slots, "recommended_slots": self.LOGICAL_SLOTS_PER_WORKER, "active_load": active, "available_slots": max(0, logical_slots - active), "last_heartbeat": float(row["last_heartbeat"])})
        ready = [item for item in worker_items if item["status"] == "ready"]
        return {"free_only": True, "worker_count": len(worker_items), "ready_workers": len(ready), "stale_workers": sum(item["status"] == "stale" for item in worker_items), "logical_slots": len(ready), "active_leases": sum(item["active_load"] for item in ready), "available_slots": sum(item["available_slots"] for item in ready), "total_cpu": sum(item["cpu_count"] for item in ready), "total_memory_mb": sum(item["memory_mb"] for item in ready), "workers": worker_items}
