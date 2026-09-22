"""Authenticated free compute coordinator for remote lead-processing workers.

The coordinator is the only component that owns the shared task state. Remote
workers never open the coordinator SQLite database directly. The service uses
only the Python standard library and an operator-provided bearer token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from .compute_inventory import ComputeInventory
from .compute_pool import ComputePool, WorkerIdentity
from .compute_provider import ProviderResourceSnapshot
from .compute_resources import ComputeRequirements, CpuResource, GpuResource, GpuRequirements, NodeResource, ResourceState, WorkloadClass
from .compute_scheduler import ComputeScheduler, ComputeSchedulingError
from .nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


class ComputeCoordinator:
    def __init__(self, db_path: str, auth_token: str, lease_seconds: int = 300, inventory: ComputeInventory | None = None):
        if not auth_token:
            raise ValueError("auth_token is required")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.db_path = db_path
        self.auth_token = auth_token
        self.pool = ComputePool(db_path, lease_seconds=lease_seconds)
        self.lease_seconds = lease_seconds
        inventory_path = os.environ.get("THORIO_COMPUTE_INVENTORY_DB", f"{db_path}.inventory.sqlite3")
        self.inventory = inventory or ComputeInventory(inventory_path)
        self.compute_scheduler = ComputeScheduler(self.inventory)
        self._lock = threading.RLock()
        self._initialize_tasks()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_tasks(self) -> None:
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_tasks (
                task_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                worker_id TEXT,
                lease_token TEXT,
                lease_until REAL,
                result TEXT,
                error TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                attempt_id TEXT,
                generation INTEGER NOT NULL DEFAULT 0,
                completed_worker_id TEXT,
                completed_lease_digest TEXT,
                completed_result_digest TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL)""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(compute_tasks)")}
            migrations = {
                "attempts": "ALTER TABLE compute_tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
                "attempt_id": "ALTER TABLE compute_tasks ADD COLUMN attempt_id TEXT",
                "generation": "ALTER TABLE compute_tasks ADD COLUMN generation INTEGER NOT NULL DEFAULT 0",
                "completed_worker_id": "ALTER TABLE compute_tasks ADD COLUMN completed_worker_id TEXT",
                "completed_lease_digest": "ALTER TABLE compute_tasks ADD COLUMN completed_lease_digest TEXT",
                "completed_result_digest": "ALTER TABLE compute_tasks ADD COLUMN completed_result_digest TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_execution_attempts (
                attempt_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                worker_id TEXT NOT NULL,
                status TEXT NOT NULL,
                lease_token_digest TEXT NOT NULL,
                started_at REAL NOT NULL,
                finished_at REAL,
                error TEXT NOT NULL DEFAULT '',
                provider_id TEXT,
                domain_id TEXT,
                resource_ids TEXT NOT NULL DEFAULT '[]',
                checkpoint_ref TEXT,
                artifact_refs TEXT NOT NULL DEFAULT '[]',
                verification TEXT,
                authoritative_acceptance TEXT NOT NULL DEFAULT 'pending',
                allocation_id TEXT
            )""")
            attempt_columns = {row[1] for row in connection.execute("PRAGMA table_info(compute_execution_attempts)")}
            if "allocation_id" not in attempt_columns:
                connection.execute("ALTER TABLE compute_execution_attempts ADD COLUMN allocation_id TEXT")
            if "rendezvous_endpoint" not in attempt_columns:
                connection.execute("ALTER TABLE compute_execution_attempts ADD COLUMN rendezvous_endpoint TEXT")
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_execution_participants (
                attempt_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                allocation_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                world_size INTEGER NOT NULL,
                rendezvous_ref TEXT NOT NULL,
                status TEXT NOT NULL,
                resource_ids TEXT NOT NULL DEFAULT '[]',
                bound_at REAL NOT NULL,
                heartbeat_at REAL NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                verification TEXT,
                finished_at REAL,
                PRIMARY KEY (attempt_id, worker_id),
                UNIQUE (attempt_id, rank),
                UNIQUE (attempt_id, node_id)
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_participants_task ON compute_execution_participants(task_id, generation)")
            participant_columns = {row[1] for row in connection.execute("PRAGMA table_info(compute_execution_participants)")}
            if "verification" not in participant_columns:
                connection.execute("ALTER TABLE compute_execution_participants ADD COLUMN verification TEXT")
            if "finished_at" not in participant_columns:
                connection.execute("ALTER TABLE compute_execution_participants ADD COLUMN finished_at REAL")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_participants_status ON compute_execution_participants(status, heartbeat_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_tasks_status ON compute_tasks(status, created_at)")
            connection.execute("""CREATE TABLE IF NOT EXISTS compute_task_checkpoints (
                task_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                result TEXT,
                worker_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (task_id, item_key)
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_task_checkpoints_task_index ON compute_task_checkpoints(task_id, item_index)")
            connection.commit()

    @staticmethod
    def _checkpoint_item_key(item: Any) -> str:
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _claim_checkpointed_payload(self, connection: sqlite3.Connection, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if str(payload.get("kind") or "").strip() != "lead_prepare":
            return payload
        leads = payload.get("leads")
        if not isinstance(leads, list):
            return payload
        rows = connection.execute(
            "SELECT item_key FROM compute_task_checkpoints WHERE task_id=?",
            (task_id,),
        ).fetchall()
        completed = {str(row["item_key"]) for row in rows}
        pending = []
        for lead in leads:
            if not isinstance(lead, dict):
                raise ValueError("lead_prepare leads must contain objects")
            item_key = self._checkpoint_item_key(lead)
            if item_key in completed:
                continue
            item = dict(lead)
            item["__checkpoint_item_key"] = item_key
            pending.append(item)
        claimed_payload = dict(payload)
        claimed_payload["leads"] = pending
        return claimed_payload

    def checkpoint_lead_prepare(
        self,
        worker_id: str,
        task_id: str,
        lease_token: str,
        items: list[Dict[str, Any]],
    ) -> Dict[str, int]:
        if not isinstance(items, list) or not items:
            raise ValueError("checkpoint items must be a non-empty list")
        with self._lock:
            with self._connect() as connection:
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    raise ValueError("invalid or expired task lease")
                task_row = connection.execute(
                    "SELECT payload,generation FROM compute_tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if task_row is None:
                    raise ValueError("task not found")
                payload = json.loads(task_row["payload"])
                if str(payload.get("kind") or "").strip() != "lead_prepare":
                    raise ValueError("checkpoints are only supported for lead_prepare tasks")
                leads = payload.get("leads")
                if not isinstance(leads, list):
                    raise ValueError("lead_prepare requires a leads list")
                item_index = {
                    self._checkpoint_item_key(lead): index
                    for index, lead in enumerate(leads)
                    if isinstance(lead, dict)
                }
                now = time.time()
                checkpointed = 0
                already = 0
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("checkpoint items must be objects")
                    key = str(item.get("item_key") or "").strip()
                    if not key or key not in item_index:
                        raise ValueError("checkpoint item does not belong to the task")
                    result = item.get("result")
                    if result is not None and not isinstance(result, dict):
                        raise ValueError("checkpoint result must be an object or null")
                    serialized = None if result is None else json.dumps(result, ensure_ascii=False, sort_keys=True)
                    existing = connection.execute(
                        "SELECT result FROM compute_task_checkpoints WHERE task_id=? AND item_key=?",
                        (task_id, key),
                    ).fetchone()
                    if existing is not None:
                        if existing["result"] != serialized:
                            raise ValueError(f"checkpoint conflict for item {key}")
                        already += 1
                        continue
                    connection.execute(
                        """INSERT INTO compute_task_checkpoints
                           (task_id,item_key,item_index,result,worker_id,generation,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (task_id, key, item_index[key], serialized, worker_id, int(task_row["generation"]), now, now),
                    )
                    checkpointed += 1
                connection.commit()
                return {"checkpointed": checkpointed, "already_checkpointed": already}

    def checkpoint_results(self, task_id: str) -> Dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT item_key,item_index,result FROM compute_task_checkpoints WHERE task_id=? ORDER BY item_index",
                (task_id,),
            ).fetchall()
        results = [json.loads(row["result"]) for row in rows if row["result"] is not None]
        return {"completed": len(rows), "results": results}

    def enqueue(self, payload: Dict[str, Any], task_id: Optional[str] = None) -> str:
        if not isinstance(payload, dict):
            raise ValueError("task payload must be an object")
        resolved_id = task_id or str(uuid.uuid4())
        if not isinstance(resolved_id, str) or not resolved_id.strip():
            raise ValueError("task_id must be a non-empty string")
        now = time.time()
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self._connect() as connection:
                existing = connection.execute("SELECT payload,status FROM compute_tasks WHERE task_id=?", (resolved_id,)).fetchone()
                if existing:
                    if json.dumps(json.loads(existing["payload"]), ensure_ascii=False, sort_keys=True) != serialized:
                        raise ValueError(f"task_id already exists with a different payload: {resolved_id}")
                    return resolved_id
                connection.execute("INSERT INTO compute_tasks(task_id,payload,created_at,updated_at) VALUES(?,?,?,?)", (resolved_id, serialized, now, now))
                connection.commit()
        return resolved_id

    def task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    @staticmethod
    def _gpu_resources_from_payload(value: Any, worker_id: str) -> tuple[GpuResource, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise ValueError("gpu_resources must be a list")
        result: list[GpuResource] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("gpu_resources entries must be objects")
            result.append(GpuResource(
                node_id=str(item.get("node_id") or worker_id),
                gpu_id=str(item["gpu_id"]),
                gpu_uuid=item.get("gpu_uuid"),
                model=item.get("model"),
                vram_bytes=item.get("vram_bytes"),
                compute_capability=item.get("compute_capability"),
                driver_version=item.get("driver_version"),
                cuda_version=item.get("cuda_version"),
                pci_bus_id=item.get("pci_bus_id"),
                numa_node=item.get("numa_node"),
                nvlink_domain=item.get("nvlink_domain"),
                topology_domain=item.get("topology_domain"),
                health_state=ResourceState(str(item.get("health_state", ResourceState.DISCOVERED.value))),
                availability_state=ResourceState(str(item.get("availability_state", ResourceState.DISCOVERED.value))),
            ))
        return tuple(result)

    def _observe_worker_resources(self, identity: WorkerIdentity) -> None:
        now = time.time()
        node_state = ResourceState.DEGRADED if identity.gpu_discovery_state == "degraded" else ResourceState.AVAILABLE
        evidence = {
            "source": "authenticated_worker_registration",
            "worker_id": identity.worker_id,
            "gpu_discovery_state": identity.gpu_discovery_state,
            "gpu_discovery_error": identity.gpu_discovery_error,
            "gpu_count": len(identity.gpu_resources),
            "hardware_attestation": "worker-local-nvidia-discovery",
        }
        snapshot = ProviderResourceSnapshot(
            provider_id="worker_pool",
            domain_id=identity.worker_id,
            observed_at=now,
            expires_at=now + max(60, self.lease_seconds * 2),
            ephemeral=True,
            authentication_state="authenticated",
            evidence=evidence,
            nodes=(NodeResource(
                node_id=identity.worker_id,
                architecture=identity.architecture,
                cpu=CpuResource(identity.worker_id, identity.cpu_count, identity.memory_mb * 1024 * 1024),
                gpus=identity.gpu_resources,
                driver_version=identity.driver_version,
                cuda_version=identity.cuda_version,
                nccl_version=identity.nccl_version,
                nic_names=identity.nic_names,
                state=node_state,
            ),),
        )
        self.inventory.observe(snapshot)

    def register_worker(self, identity: WorkerIdentity) -> Dict[str, Any]:
        result = self.pool.register(identity)
        self._observe_worker_resources(identity)
        return result

    def heartbeat(self, worker_id: str, current_load: int = 0) -> bool:
        ok = self.pool.heartbeat(worker_id, current_load)
        if ok:
            worker = self.pool.worker(worker_id)
            if worker:
                self._observe_worker_resources(WorkerIdentity(
                    worker_id=worker["worker_id"], hostname=worker["hostname"], architecture=worker["architecture"],
                    cpu_count=int(worker["cpu_count"]), memory_mb=int(worker["memory_mb"]),
                    capabilities=tuple(worker.get("capabilities", ())),
                    gpu_resources=tuple(worker.get("gpu_resources", ())),
                    driver_version=worker.get("driver_version"), cuda_version=worker.get("cuda_version"),
                    nccl_version=worker.get("nccl_version"), nic_names=tuple(worker.get("nic_names", ())),
                    gpu_discovery_state=str(worker.get("gpu_discovery_state", "not_probed")),
                    gpu_discovery_error=str(worker.get("gpu_discovery_error", "")),
                ))
        return ok

    @staticmethod
    def _required_capabilities(payload: Dict[str, Any]) -> tuple[str, ...]:
        explicit = payload.get("required_capabilities")
        if explicit is not None:
            if not isinstance(explicit, (list, tuple, set)) or not all(isinstance(item, str) and item.strip() for item in explicit):
                raise ValueError("required_capabilities must be a sequence of non-empty strings")
            return tuple(dict.fromkeys(item.strip() for item in explicit))
        kind = str(payload.get("kind") or "").strip()
        if kind == "lead_prepare":
            return ("lead_prepare",)
        if kind == "agent_task":
            agent = str(payload.get("agent") or payload.get("role") or "").strip()
            if agent:
                return (agent,)
        return ()

    @staticmethod
    def _worker_supports(worker: Dict[str, Any], required: tuple[str, ...]) -> bool:
        capabilities = {str(item).strip() for item in worker.get("capabilities", []) if str(item).strip()}
        return all(capability in capabilities for capability in required)

    @staticmethod
    def _requirements_from_payload(payload: Dict[str, Any], worker_id: str | None = None) -> ComputeRequirements:
        raw = payload.get("compute_requirements") or {}
        if not isinstance(raw, dict):
            raise ValueError("compute_requirements must be an object")
        workload_name = str(raw.get("workload_class", WorkloadClass.CPU_BOUND.value)).strip()
        try:
            workload_class = WorkloadClass(workload_name)
        except ValueError as exc:
            raise ValueError(f"unsupported workload_class: {workload_name}") from exc
        gpu_raw = raw.get("gpu", {})
        if not isinstance(gpu_raw, dict):
            raise ValueError("compute_requirements.gpu must be an object")
        gpu = GpuRequirements(
            gpu_count=int(gpu_raw.get("gpu_count", 0)),
            min_vram_bytes=gpu_raw.get("min_vram_bytes"),
            min_compute_capability=gpu_raw.get("min_compute_capability"),
            required_cuda_version=gpu_raw.get("required_cuda_version"),
            required_driver_version=gpu_raw.get("required_driver_version"),
            required_nvlink_domain=gpu_raw.get("required_nvlink_domain"),
            require_nccl=bool(gpu_raw.get("require_nccl", False)),
        )
        requested_nodes = raw.get("allowed_node_ids")
        if requested_nodes is not None and (not isinstance(requested_nodes, (list, tuple)) or any(not isinstance(item, str) for item in requested_nodes)):
            raise ValueError("compute_requirements.allowed_node_ids must be a sequence of strings")
        if worker_id is None:
            allowed = tuple(dict.fromkeys(str(item) for item in requested_nodes)) if requested_nodes is not None else ()
        else:
            allowed = (worker_id,) if requested_nodes is None else tuple(dict.fromkeys(str(item) for item in requested_nodes))
            if allowed != (worker_id,):
                raise ValueError("compute_requirements.allowed_node_ids must match the claiming worker")
        return ComputeRequirements(
            workload_class=workload_class,
            gpu=gpu,
            min_cpu_count=int(raw.get("min_cpu_count", 1)),
            min_memory_bytes=int(raw.get("min_memory_bytes", 1)),
            same_node=bool(raw.get("same_node", True)),
            topology_domain=raw.get("topology_domain"),
            allowed_node_ids=allowed,
        )

    def physical_requirements(self, payload: Dict[str, Any]) -> ComputeRequirements:
        """Translate a queued task into global physical-fabric requirements.

        This is an additive scheduling seam. It deliberately does not lease the
        task, bind an execution attempt, or mutate authoritative business state.
        The legacy claim() path remains worker-local until distributed execution
        is independently verified.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        return self._requirements_from_payload(payload, None)

    def _release_physical_allocation(self, attempt: Dict[str, Any] | None, reason: str) -> None:
        if not attempt or not attempt.get("allocation_id"):
            return
        self.inventory.release_allocation(str(attempt["allocation_id"]), task_id=str(attempt["task_id"]), attempt_id=str(attempt["attempt_id"]), generation=int(attempt["generation"]), reason=reason)


    def claim_physical(self) -> Optional[Dict[str, Any]]:
        """Lease the next physically schedulable task without pinning it to one worker.

        The returned execution identity represents the fabric lease, not a
        compute worker. Concrete workers participating in the allocation are
        identified by the exact physical resource/node IDs returned by the
        physical scheduler. The legacy claim(worker_id) path remains unchanged.
        """
        with self._lock:
            self.recover_expired_tasks()
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT task_id,payload FROM compute_tasks "
                    "WHERE status='queued' AND payload LIKE '%compute_requirements%' "
                    "ORDER BY created_at,task_id LIMIT 100"
                ).fetchall()
                selected = None
                payload = None
                for row in rows:
                    candidate = json.loads(row["payload"])
                    if "compute_requirements" not in candidate:
                        continue
                    try:
                        self.physical_requirements(candidate)
                    except (TypeError, ValueError):
                        continue
                    selected = row
                    payload = candidate
                    break
                if selected is None:
                    connection.rollback()
                    return None

                task_id = str(selected["task_id"])
                lease_token = str(uuid.uuid4())
                attempt_id = str(uuid.uuid4())
                execution_identity = f"fabric:{attempt_id}"
                now = time.time()
                generation_row = connection.execute(
                    "SELECT generation FROM compute_tasks WHERE task_id=? AND status='queued'",
                    (task_id,),
                ).fetchone()
                if not generation_row:
                    connection.rollback()
                    return None
                generation = int(generation_row["generation"]) + 1
                updated = connection.execute(
                    "UPDATE compute_tasks SET status='leased',worker_id=?,lease_token=?,"
                    "lease_until=?,attempts=attempts+1,attempt_id=?,generation=?,updated_at=? "
                    "WHERE task_id=? AND status='queued'",
                    (
                        execution_identity,
                        lease_token,
                        now + self.lease_seconds,
                        attempt_id,
                        generation,
                        now,
                        task_id,
                    ),
                )
                if updated.rowcount != 1:
                    connection.rollback()
                    return None
                lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
                connection.execute(
                    "INSERT INTO compute_execution_attempts("
                    "attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at"
                    ") VALUES(?,?,?,?,?,?,?)",
                    (
                        attempt_id,
                        task_id,
                        generation,
                        execution_identity,
                        "leased",
                        lease_digest,
                        now,
                    ),
                )
                connection.commit()

            allocation = None
            try:
                requirements = self.physical_requirements(payload)
                allocation_id = f"{task_id}:{attempt_id}"
                allocation = self.compute_scheduler.allocate(requirements, allocation_id)
                if not self.inventory.bind_allocation(
                    allocation.allocation_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    generation=generation,
                    lease_token_digest=lease_digest,
                ):
                    raise ComputeSchedulingError(
                        "physical allocation could not be bound to execution attempt"
                    )
                if not self.bind_physical_allocation(
                    task_id=task_id,
                    attempt_id=attempt_id,
                    generation=generation,
                    allocation_id=allocation.allocation_id,
                    provider_id=allocation.provider_id,
                    domain_id=allocation.domain_id,
                    resource_ids=allocation.resource_ids,
                    lease_token=lease_token,
                ):
                    self._release_physical_allocation(
                        {
                            "allocation_id": allocation.allocation_id,
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "generation": generation,
                        },
                        "fabric binding rejected",
                    )
                    self.release(execution_identity, task_id, lease_token, "fabric binding rejected")
                    return None
                if not self.bind_execution_participants(
                    task_id=task_id,
                    attempt_id=attempt_id,
                    generation=generation,
                    allocation_id=allocation.allocation_id,
                    provider_id=allocation.provider_id,
                    domain_id=allocation.domain_id,
                    node_ids=allocation.node_ids,
                    resource_ids=allocation.resource_ids,
                    lease_token=lease_token,
                    rendezvous_ref=f"fabric:{attempt_id}:{generation}",
                ):
                    self._release_physical_allocation(
                        {"allocation_id": allocation.allocation_id, "task_id": task_id, "attempt_id": attempt_id, "generation": generation},
                        "participant binding rejected",
                    )
                    self.release(execution_identity, task_id, lease_token, "participant binding rejected")
                    return None
            except Exception as error:
                if allocation is not None:
                    self._release_physical_allocation(
                        {
                            "allocation_id": allocation.allocation_id,
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "generation": generation,
                        },
                        f"physical allocation failed: {error}",
                    )
                self.release(
                    execution_identity,
                    task_id,
                    lease_token,
                    f"physical allocation unavailable: {error}",
                )
                return None

            return {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "generation": generation,
                "execution_identity": execution_identity,
                "payload": payload,
                "lease_token": lease_token,
                "physical_allocation": {
                    "allocation_id": allocation.allocation_id,
                    "provider_id": allocation.provider_id,
                    "domain_id": allocation.domain_id,
                    "node_ids": list(allocation.node_ids),
                    "resource_ids": list(allocation.resource_ids),
                    "resource_keys": list(allocation.resource_keys),
                    "capability_evidence": list(allocation.capability_evidence),
                },
            }

    def claim(self, worker_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.pool.reap_stale_workers()
            self.recover_expired_tasks()
            worker = self.pool.worker(worker_id)
            if not worker or worker["status"] != "ready":
                return None
            if not self.pool.reserve_task_slot(worker_id):
                return None
            with self._connect() as connection:
                selected = None
                offset = 0
                while selected is None:
                    rows = connection.execute("SELECT task_id,payload FROM compute_tasks WHERE status='queued' ORDER BY created_at,task_id LIMIT 100 OFFSET ?", (offset,)).fetchall()
                    if not rows:
                        break
                    for row in rows:
                        payload = json.loads(row["payload"])
                        required = self._required_capabilities(payload)
                        if self._worker_supports(worker, required):
                            selected = row
                            break
                    offset += len(rows)
                if selected is None:
                    connection.rollback()
                    self.pool.release_task_slot(worker_id)
                    return None
                task_id = selected["task_id"]
                lease_token = str(uuid.uuid4())
                now = time.time()
                generation = int(connection.execute("SELECT generation FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()["generation"]) + 1
                attempt_id = str(uuid.uuid4())
                updated = connection.execute("UPDATE compute_tasks SET status='leased',worker_id=?,lease_token=?,lease_until=?,attempts=attempts+1,attempt_id=?,generation=?,updated_at=? WHERE task_id=? AND status='queued'", (worker_id, lease_token, now + self.lease_seconds, attempt_id, generation, now, task_id))
                if updated.rowcount != 1:
                    connection.rollback(); self.pool.release_task_slot(worker_id); return None
                lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
                connection.execute("INSERT INTO compute_execution_attempts(attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at) VALUES(?,?,?,?,?,?,?)", (attempt_id, task_id, generation, worker_id, "leased", lease_digest, now))
                connection.commit()
            payload = json.loads(selected["payload"])
            with self._connect() as checkpoint_connection:
                payload = self._claim_checkpointed_payload(checkpoint_connection, task_id, payload)
            allocation = None
            if "compute_requirements" in payload:
                allocation_id = f"{task_id}:{attempt_id}"
                try:
                    requirements = self._requirements_from_payload(payload, worker_id)
                    allocation = self.compute_scheduler.allocate(requirements, allocation_id)
                    lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
                    if not self.inventory.bind_allocation(allocation.allocation_id, task_id=task_id, attempt_id=attempt_id, generation=generation, lease_token_digest=lease_digest):
                        raise ComputeSchedulingError("physical allocation could not be bound to execution attempt")
                    if not self.bind_physical_allocation(task_id=task_id, attempt_id=attempt_id, generation=generation, allocation_id=allocation.allocation_id, provider_id=allocation.provider_id, domain_id=allocation.domain_id, resource_ids=allocation.resource_ids, lease_token=lease_token):
                        self._release_physical_allocation({"allocation_id": allocation.allocation_id, "task_id": task_id, "attempt_id": attempt_id, "generation": generation}, "coordinator binding rejected")
                        self.release(worker_id, task_id, lease_token, "physical binding rejected")
                        return None
                    if not self.bind_execution_participants(
                        task_id=task_id,
                        attempt_id=attempt_id,
                        generation=generation,
                        allocation_id=allocation.allocation_id,
                        provider_id=allocation.provider_id,
                        domain_id=allocation.domain_id,
                        node_ids=allocation.node_ids,
                        resource_ids=allocation.resource_ids,
                        lease_token=lease_token,
                        rendezvous_ref=f"worker:{worker_id}:{attempt_id}:{generation}",
                    ):
                        self._release_physical_allocation(
                            {"allocation_id": allocation.allocation_id, "task_id": task_id, "attempt_id": attempt_id, "generation": generation},
                            "participant binding rejected",
                        )
                        self.release(worker_id, task_id, lease_token, "participant binding rejected")
                        return None
                except Exception as error:
                    if allocation is not None:
                        self._release_physical_allocation({"allocation_id": allocation.allocation_id, "task_id": task_id, "attempt_id": attempt_id, "generation": generation}, f"physical allocation failed: {error}")
                    self.release(worker_id, task_id, lease_token, f"physical allocation unavailable: {error}")
                    return None
            return {"task_id": task_id, "attempt_id": attempt_id, "generation": generation, "payload": payload, "lease_token": lease_token,
                    "physical_allocation": None if allocation is None else {"allocation_id": allocation.allocation_id, "provider_id": allocation.provider_id, "domain_id": allocation.domain_id, "node_ids": list(allocation.node_ids), "resource_ids": list(allocation.resource_ids), "resource_keys": list(allocation.resource_keys), "capability_evidence": list(allocation.capability_evidence)}}

    def execution_attempt_for_allocation(self, allocation_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM compute_execution_attempts WHERE allocation_id=? ORDER BY generation DESC LIMIT 1", (allocation_id,)).fetchone()
        if not row:
            return None
        item = dict(row); item["resource_ids"] = json.loads(item["resource_ids"] or "[]"); item["artifact_refs"] = json.loads(item["artifact_refs"] or "[]"); return item

    def execution_attempt(self, attempt_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM compute_execution_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if not row:
            return None
        item = dict(row); item["resource_ids"] = json.loads(item["resource_ids"] or "[]"); item["artifact_refs"] = json.loads(item["artifact_refs"] or "[]"); return item

    def bind_physical_allocation(self, *, task_id: str, attempt_id: str, generation: int, allocation_id: str, provider_id: str, domain_id: str, resource_ids: list[str] | tuple[str, ...], lease_token: str) -> bool:
        if not task_id.strip() or not attempt_id.strip() or not allocation_id.strip():
            raise ValueError("task, attempt, and allocation identities are required")
        if generation < 1 or not provider_id.strip() or not domain_id.strip() or not resource_ids:
            raise ValueError("complete physical allocation metadata is required")
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        serialized_ids = json.dumps(tuple(dict.fromkeys(str(item) for item in resource_ids)), ensure_ascii=False)
        with self._lock:
            with self._connect() as connection:
                row = connection.execute("""SELECT a.status,a.task_id,a.generation,a.worker_id,a.lease_token_digest,a.allocation_id,a.provider_id,a.domain_id,a.resource_ids
                   FROM compute_execution_attempts a JOIN compute_tasks t ON t.attempt_id=a.attempt_id
                   WHERE a.attempt_id=? AND a.task_id=?""", (attempt_id, task_id)).fetchone()
                if not row or row["generation"] != generation or row["status"] != "leased" or row["lease_token_digest"] != lease_digest:
                    return False
                if row["allocation_id"]:
                    return bool(row["allocation_id"] == allocation_id and row["provider_id"] == provider_id and row["domain_id"] == domain_id and row["resource_ids"] == serialized_ids)
                cursor = connection.execute("""UPDATE compute_execution_attempts SET allocation_id=?,provider_id=?,domain_id=?,resource_ids=?
                       WHERE attempt_id=? AND task_id=? AND generation=? AND status='leased' AND allocation_id IS NULL""", (allocation_id, provider_id, domain_id, serialized_ids, attempt_id, task_id, generation))
                if cursor.rowcount != 1:
                    connection.rollback(); return False
                connection.commit(); return True

    def execution_participants(self, attempt_id: str) -> list[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM compute_execution_participants WHERE attempt_id=? ORDER BY rank",
                (attempt_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["resource_ids"] = json.loads(item["resource_ids"] or "[]")
            result.append(item)
        return result

    def bind_execution_participants(
        self,
        *,
        task_id: str,
        attempt_id: str,
        generation: int,
        allocation_id: str,
        provider_id: str,
        domain_id: str,
        node_ids: list[str] | tuple[str, ...],
        resource_ids: list[str] | tuple[str, ...],
        lease_token: str,
        rendezvous_ref: str | None = None,
    ) -> list[Dict[str, Any]]:
        """Bind exact registered workers to an exact physical allocation.

        Node IDs are the physical participant identity at this boundary. Each
        node must currently map to a registered ready worker. Rank assignment
        follows the scheduler's deterministic node order and world size equals
        the exact participant count. The rendezvous value is an opaque durable
        reference, not a claim that a transport has been established.
        """
        if not task_id.strip() or not attempt_id.strip() or not allocation_id.strip():
            raise ValueError("task, attempt, and allocation identities are required")
        if generation < 1 or not provider_id.strip() or not domain_id.strip():
            raise ValueError("provider, domain, and generation are required")
        nodes = tuple(dict.fromkeys(str(item) for item in node_ids if str(item).strip()))
        resources = tuple(dict.fromkeys(str(item) for item in resource_ids if str(item).strip()))
        if not nodes or len(nodes) != len(tuple(node_ids)):
            raise ValueError("node_ids must contain unique non-empty node identities")
        if not resources:
            raise ValueError("resource_ids must not be empty")
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        rendezvous = str(rendezvous_ref or "").strip()
        if not rendezvous:
            raise ValueError("rendezvous_ref is required and must be a durable execution identity")

        workers = []
        for node_id in nodes:
            worker = self.pool.worker(node_id)
            if not worker or worker["status"] != "ready":
                return []
            workers.append(worker)

        allocation = self.inventory.allocation(allocation_id)
        if not allocation or allocation["state"] != "bound":
            return []
        if (
            allocation["task_id"] != task_id
            or allocation["attempt_id"] != attempt_id
            or int(allocation["generation"] or 0) != generation
            or allocation["provider_id"] != provider_id
            or allocation["domain_id"] != domain_id
            or allocation["lease_token_digest"] != lease_digest
        ):
            return []
        allocation_node_ids = tuple(
            dict.fromkeys(
                str(resource["node_id"])
                for resource_key in allocation["resource_keys"]
                for resource in [self.inventory.get(str(resource_key))]
                if resource and str(resource.get("node_id") or "").strip()
            )
        )
        if tuple(nodes) != allocation_node_ids:
            return []
        allocation_gpu_resource_ids = tuple(
            sorted(
                f'{resource["node_id"]}/{resource["gpu_id"]}'
                for resource_key in allocation["resource_keys"]
                for resource in [self.inventory.get(str(resource_key))]
                if resource and resource.get("resource_type") == "gpu"
            )
        )
        requested_gpu_resource_ids = tuple(
            sorted(resource_id for resource_id in resources if "/gpu/" in resource_id or "/gpu-" in resource_id)
        )
        if requested_gpu_resource_ids != allocation_gpu_resource_ids:
            return []

        with self._lock:
            with self._connect() as connection:
                attempt = connection.execute(
                    "SELECT status,task_id,generation,lease_token_digest,allocation_id FROM compute_execution_attempts WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                if not attempt or attempt["task_id"] != task_id or int(attempt["generation"]) != generation:
                    return []
                if attempt["status"] != "leased" or attempt["lease_token_digest"] != lease_digest or attempt["allocation_id"] != allocation_id:
                    return []

                existing = connection.execute(
                    "SELECT * FROM compute_execution_participants WHERE attempt_id=? ORDER BY rank",
                    (attempt_id,),
                ).fetchall()
                if existing:
                    existing_contract = [dict(row) for row in existing]
                    expected_workers = [node_id for node_id in nodes]
                    if [row["worker_id"] for row in existing_contract] != expected_workers:
                        return []
                    if any(
                        row["task_id"] != task_id
                        or int(row["generation"]) != generation
                        or row["allocation_id"] != allocation_id
                        or row["rendezvous_ref"] != rendezvous
                        or int(row["world_size"]) != len(nodes)
                        for row in existing_contract
                    ):
                        return []
                    return self.execution_participants(attempt_id)

                now = time.time()
                world_size = len(nodes)
                for rank, (node_id, worker) in enumerate(zip(nodes, workers)):
                    worker_resource_ids = [
                        resource_id for resource_id in resources
                        if resource_id.split("/", 1)[0] == node_id
                    ]
                    connection.execute(
                        """INSERT INTO compute_execution_participants(
                            attempt_id,task_id,generation,allocation_id,worker_id,node_id,
                            rank,world_size,rendezvous_ref,status,resource_ids,bound_at,heartbeat_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            attempt_id, task_id, generation, allocation_id, worker["worker_id"], node_id,
                            rank, world_size, rendezvous, "bound",
                            json.dumps(worker_resource_ids, ensure_ascii=False, sort_keys=True),
                            now, now,
                        ),
                    )
                connection.commit()
        return self.execution_participants(attempt_id)

    @staticmethod
    def _validate_rendezvous_endpoint(value: str) -> str:
        endpoint = str(value).strip()
        if not endpoint:
            raise ValueError("rendezvous_endpoint is required and must be host:port")
        parsed = urlsplit("//" + endpoint)
        if not parsed.hostname or parsed.port is None:
            raise ValueError("rendezvous_endpoint must be host:port")
        if not 1 <= parsed.port <= 65535:
            raise ValueError("rendezvous_endpoint port must be between 1 and 65535")
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("rendezvous_endpoint must contain only host and port")
        return endpoint

    def _bind_rendezvous_endpoint(self, attempt_id: str, generation: int, lease_token: str, endpoint: str) -> str:
        resolved = self._validate_rendezvous_endpoint(endpoint)
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT a.status,a.generation,a.lease_token_digest,a.rendezvous_endpoint
                       FROM compute_execution_attempts a
                       JOIN compute_tasks t ON t.attempt_id=a.attempt_id
                       WHERE a.attempt_id=? AND t.status='leased' AND t.lease_until > ?""",
                    (attempt_id, time.time()),
                ).fetchone()
                if not row or row["status"] != "leased" or int(row["generation"]) != generation or row["lease_token_digest"] != lease_digest:
                    raise ValueError("execution lease is not valid")
                existing = str(row["rendezvous_endpoint"] or "").strip()
                if existing and existing != resolved:
                    raise ValueError("rendezvous_endpoint does not match the durable execution endpoint")
                if not existing:
                    conflict = connection.execute(
                        """SELECT 1
                           FROM compute_execution_attempts a
                           JOIN compute_tasks t ON t.attempt_id=a.attempt_id
                           WHERE a.status='leased'
                             AND t.status='leased'
                             AND t.lease_until > ?
                             AND a.rendezvous_endpoint=?
                             AND a.attempt_id<>?
                           LIMIT 1""",
                        (time.time(), resolved, attempt_id),
                    ).fetchone()
                    if conflict:
                        raise ValueError("rendezvous_endpoint is already bound to another active execution attempt")
                    updated = connection.execute(
                        """UPDATE compute_execution_attempts
                           SET rendezvous_endpoint=?
                           WHERE attempt_id=? AND generation=? AND status='leased'
                             AND lease_token_digest=? AND rendezvous_endpoint IS NULL""",
                        (resolved, attempt_id, generation, lease_digest),
                    )
                    if updated.rowcount != 1:
                        row = connection.execute(
                            "SELECT rendezvous_endpoint FROM compute_execution_attempts WHERE attempt_id=?",
                            (attempt_id,),
                        ).fetchone()
                        existing = str(row["rendezvous_endpoint"] or "") if row else ""
                        if existing != resolved:
                            raise ValueError("rendezvous_endpoint was concurrently bound to a different endpoint")
                    else:
                        existing = resolved
                connection.commit()
        return existing or resolved

    @staticmethod
    def _planned_physical_path(resource: dict[str, Any], gpu_uuid: str) -> dict[str, Any] | None:
        paths = ComputeScheduler._verified_gpu_nic_rdma_path(resource, gpu_uuid)
        if not paths:
            return None
        path = dict(paths[0])
        link = path.pop("verified_rdma_link", None)
        if isinstance(link, dict):
            path.update({
                "rdma_pci_bus_id": link.get("pci_bus_id"),
                "rdma_link_state": link.get("state"),
                "rdma_physical_state": link.get("physical_state"),
            })
        return {
            "node_id": str(resource.get("node_id") or "").strip(),
            "gpu_uuid": gpu_uuid,
            "nic": path.get("nic"),
            "nic_pci_bus_id": path.get("nic_pci_bus_id"),
            "rdma_device": path.get("rdma_device"),
            "rdma_port": path.get("rdma_port"),
            "rdma_pci_bus_id": path.get("rdma_pci_bus_id"),
            "link_layer": path.get("link_layer"),
            "gpu_nic_distance": path.get("gpu_nic_distance"),
            "shared_pci_ancestor": path.get("shared_pci_ancestor"),
            "rdma_link_state": path.get("rdma_link_state"),
            "rdma_physical_state": path.get("rdma_physical_state"),
            "physical_evidence": path.get("physical_evidence"),
        }
    def fabric_launch_plan(self, attempt_id: str, rendezvous_endpoint: str) -> Dict[str, Any]:
        """Build the exact per-process launch contract from durable physical participants.

        Each allocated GPU becomes exactly one distributed process. Global ranks
        are assigned deterministically from the durable participant order, so
        nodes may contribute different GPU counts without violating the launch
        contract. The coordinator never treats allocation as execution proof.
        """
        endpoint = self._validate_rendezvous_endpoint(rendezvous_endpoint)
        now = time.time()
        with self._connect() as connection:
            attempt_row = connection.execute(
                """SELECT a.status,a.generation,a.lease_token_digest,a.rendezvous_endpoint,
                          t.status AS task_status,t.lease_until
                   FROM compute_execution_attempts a
                   JOIN compute_tasks t ON t.attempt_id=a.attempt_id
                   WHERE a.attempt_id=?""",
                (attempt_id,),
            ).fetchone()
        if not attempt_row:
            raise ValueError("execution attempt does not exist")
        if (
            attempt_row["status"] != "leased"
            or int(attempt_row["generation"]) < 1
            or attempt_row["task_status"] != "leased"
            or attempt_row["lease_until"] is None
            or float(attempt_row["lease_until"]) <= now
        ):
            raise ValueError("execution attempt lease is not active")
        durable_endpoint = str(attempt_row["rendezvous_endpoint"] or "").strip()
        if not durable_endpoint:
            raise ValueError("execution attempt has no durable rendezvous endpoint")
        if endpoint != durable_endpoint:
            raise ValueError("rendezvous_endpoint does not match the durable execution endpoint")

        participants = self.execution_participants(attempt_id)
        if not participants:
            raise ValueError("execution attempt has no bound participants")

        workers = []
        total_processes = 0
        for expected_node_rank, participant in enumerate(participants):
            if int(participant["rank"]) != expected_node_rank:
                raise ValueError("participant node ranks are not contiguous and deterministic")
            worker = self.pool.worker(str(participant["worker_id"]))
            if not worker or worker["status"] != "ready":
                raise ValueError(f"participant worker is not ready: {participant['worker_id']}")

            gpu_resource_ids = [
                resource_id for resource_id in participant["resource_ids"]
                if "/gpu/" in resource_id or "/gpu-" in resource_id
            ]
            if not gpu_resource_ids:
                raise ValueError(f"participant has no allocated GPU resources: {participant['worker_id']}")

            allocation = self.inventory.allocation(str(participant["allocation_id"]))
            if not allocation:
                raise ValueError(f"physical allocation is missing: {participant['allocation_id']}")
            if (
                allocation.get("state") != "bound"
                or str(allocation.get("attempt_id") or "").strip() != attempt_id
                or int(allocation.get("generation") or 0) != int(participant["generation"])
            ):
                raise ValueError(
                    f"physical allocation is not bound to execution attempt: {participant['allocation_id']}"
                )
            inventory_gpus = {}
            for resource_key in allocation["resource_keys"]:
                resource = self.inventory.get(str(resource_key))
                if not resource or resource.get("resource_type") != "gpu":
                    continue
                try:
                    payload = json.loads(resource["payload_json"])
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"allocated GPU inventory evidence is invalid: {resource_key}") from exc
                inventory_gpus[f"{resource['node_id']}/{resource['gpu_id']}"] = payload

            def gpu_sort_key(resource_id: str) -> tuple[int, str]:
                gpu_id = resource_id.rsplit("/", 1)[-1].removeprefix("gpu-")
                return (int(gpu_id) if gpu_id.isdigit() else 2**31 - 1, resource_id)

            gpu_resource_ids = sorted(gpu_resource_ids, key=gpu_sort_key)
            gpu_bindings = []
            for local_rank, resource_id in enumerate(gpu_resource_ids):
                gpu = inventory_gpus.get(resource_id)
                if gpu is None:
                    raise ValueError(
                        f"allocated GPU is not present in durable physical inventory: {resource_id}"
                    )
                gpu_uuid = str(gpu.get("gpu_uuid") or "").strip()
                gpu_id = str(gpu.get("gpu_id") or "").strip()
                if not gpu_uuid or not gpu_id:
                    raise ValueError(
                        f"allocated GPU lacks immutable physical identity: {resource_id}"
                    )
                binding = {
                    "resource_id": resource_id,
                    "gpu_id": gpu_id,
                    "gpu_uuid": gpu_uuid,
                    "pci_bus_id": gpu.get("pci_bus_id"),
                    "rank": total_processes + local_rank,
                    "local_rank": local_rank,
                }
                bound_resource = next(
                    (
                        self.inventory.get(str(resource_key))
                        for resource_key in allocation["resource_keys"]
                        if (
                            (self.inventory.get(str(resource_key)) or {}).get("resource_type") == "gpu"
                            and str((self.inventory.get(str(resource_key)) or {}).get("node_id") or "") + "/"
                            + str((self.inventory.get(str(resource_key)) or {}).get("gpu_id") or "") == resource_id
                        )
                    ),
                    None,
                )
                if bound_resource is not None:
                    if bound_resource.get("state") != ResourceState.RESERVED.value:
                        raise ValueError(
                            f"allocated GPU is not currently reserved for execution: {resource_id}"
                        )
                    planned_path = self._planned_physical_path(bound_resource, gpu_uuid)
                    if planned_path is not None:
                        if self.inventory.is_fabric_path_quarantined(planned_path):
                            raise ValueError(
                                f"allocated GPU physical path is quarantined before launch: {resource_id}"
                            )
                        binding["planned_physical_path"] = planned_path
                gpu_bindings.append(binding)

            process_count = len(gpu_bindings)
            workers.append({
                "worker_id": participant["worker_id"],
                "node_id": participant["node_id"],
                "node_rank": expected_node_rank,
                "process_count": process_count,
                "gpu_resource_ids": gpu_resource_ids,
                "gpu_bindings": gpu_bindings,
                "rendezvous_ref": participant["rendezvous_ref"],
                "rendezvous_endpoint": endpoint,
            })
            total_processes += process_count

        if total_processes < 2:
            raise ValueError("distributed launch requires at least two allocated GPU processes")
        if sorted(
            binding["rank"]
            for worker in workers
            for binding in worker["gpu_bindings"]
        ) != list(range(total_processes)):
            raise ValueError("distributed process ranks are not contiguous")
        return {
            "attempt_id": attempt_id,
            "rendezvous_endpoint": durable_endpoint,
            "world_size": total_processes,
            "nnodes": len(workers),
            "rendezvous_id": participants[0]["rendezvous_ref"],
            "workers": workers,
        }

    def _set_execution_participant_status(self, attempt_id: str, status: str, error: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE compute_execution_participants SET status=?,last_error=? WHERE attempt_id=?",
                (status, str(error)[:4000], attempt_id),
            )
            connection.commit()

    def fabric_assignments(self, worker_id: str) -> list[Dict[str, Any]]:
        """Return live participant assignments for one registered worker."""
        worker_id = str(worker_id).strip()
        if not worker_id:
            raise ValueError("worker_id is required")
        now = time.time()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT p.*, t.payload, t.lease_token, t.lease_until
                   FROM compute_execution_participants p
                   JOIN compute_tasks t ON t.task_id=p.task_id
                   JOIN compute_execution_attempts a ON a.attempt_id=p.attempt_id
                   WHERE p.worker_id=? AND p.status IN ('bound','active','launching','running')
                     AND a.status='leased' AND t.status='leased' AND t.lease_until > ?
                   ORDER BY p.bound_at,p.attempt_id""",
                (worker_id, now),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            item["resource_ids"] = json.loads(item["resource_ids"] or "[]")
            result.append(item)
        return result

    def execution_participant_state(
        self, *, attempt_id: str, generation: int, worker_id: str,
        lease_token: str, status: str, error: str = "",
    ) -> bool:
        allowed = {"bound", "launching", "active", "running", "failed"}
        if status not in allowed:
            raise ValueError(f"unsupported participant status: {status}")
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """UPDATE compute_execution_participants
                       SET heartbeat_at=?,status=?,last_error=?
                       WHERE attempt_id=? AND generation=? AND worker_id=?
                       AND (
                           status=?
                           OR (status='bound' AND ? IN ('launching','failed'))
                           OR (status='launching' AND ? IN ('active','failed'))
                           OR (status='active' AND ? IN ('running','failed'))
                           OR (status='running' AND ? = 'failed')
                       )
                       AND EXISTS (
                           SELECT 1 FROM compute_execution_attempts a
                           WHERE a.attempt_id=compute_execution_participants.attempt_id
                           AND a.task_id=compute_execution_participants.task_id
                           AND a.generation=compute_execution_participants.generation
                           AND a.status='leased' AND a.lease_token_digest=?
                           AND EXISTS (
                               SELECT 1 FROM compute_tasks t
                               WHERE t.task_id=compute_execution_participants.task_id
                               AND t.status='leased' AND t.lease_until > ?
                           )
                       )""",
                    (now, status, str(error)[:4000], attempt_id, generation, worker_id, status, status, status, status, status, lease_digest, now),
                )
                changed = cursor.rowcount == 1
                connection.commit()
            if changed and status == "failed":
                self.reconcile_fabric(participant_timeout_seconds=0.000001)
            return changed

    def _quarantine_allocation_gpu_for_path_failure(
        self,
        allocation_id: str,
        gpu_uuid: str,
        *,
        reason: str,
        evidence: dict[str, Any],
    ) -> None:
        allocation = self.inventory.allocation(allocation_id)
        if not allocation:
            return
        for resource_key in allocation["resource_keys"]:
            resource = self.inventory.get(str(resource_key))
            if not resource or resource.get("resource_type") != "gpu":
                continue
            try:
                payload = json.loads(resource.get("payload_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if str(payload.get("gpu_uuid") or "").strip() != gpu_uuid:
                continue
            planned_path = evidence.get("planned_physical_path")
            if isinstance(planned_path, dict):
                try:
                    self.inventory.quarantine_fabric_path(
                        planned_path,
                        reason=reason,
                        evidence=evidence,
                    )
                    return
                except ValueError:
                    pass
            self.inventory.quarantine_resource(
                str(resource_key),
                reason=reason,
                evidence=evidence,
            )
            return

    def record_execution_verification(
        self, *, attempt_id: str, generation: int, worker_id: str,
        lease_token: str, verification: Dict[str, Any],
    ) -> bool:
        """Accept only evidence that matches the durable per-GPU launch contract."""
        if not isinstance(verification, dict) or not verification:
            raise ValueError("verification must be a non-empty object")

        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT a.status,a.task_id,a.generation,a.lease_token_digest,
                              a.rendezvous_endpoint,p.status AS participant_status,
                              p.resource_ids,p.allocation_id
                       FROM compute_execution_attempts a
                       JOIN compute_execution_participants p
                         ON p.attempt_id=a.attempt_id AND p.generation=a.generation
                       WHERE a.attempt_id=? AND a.generation=? AND p.worker_id=?
                         AND EXISTS (
                             SELECT 1 FROM compute_tasks t
                             WHERE t.task_id=a.task_id AND t.status='leased' AND t.lease_until > ?
                         )""",
                    (attempt_id, generation, worker_id, now),
                ).fetchone()
                if (
                    not row
                    or row["status"] != "leased"
                    or row["participant_status"] not in {"bound", "launching", "active", "running"}
                    or row["lease_token_digest"] != lease_digest
                ):
                    return False

            endpoint = str(row["rendezvous_endpoint"] or "").strip()
            if not endpoint:
                return False
            try:
                launch = self.fabric_launch_plan(attempt_id, endpoint)
            except (KeyError, TypeError, ValueError):
                return False

            participant = next(
                (item for item in launch["workers"] if item["worker_id"] == worker_id),
                None,
            )
            if participant is None:
                return False

            if (
                verification.get("verified") is not True
                or verification.get("backend") != "nccl"
                or verification.get("collective") != "all_reduce"
                or verification.get("worker_id") != worker_id
                or int(verification.get("world_size", -1)) != int(launch["world_size"])
                or not isinstance(verification.get("gpu_identity"), dict)
                or verification["gpu_identity"].get("verified") is not True
            ):
                return False

            if int(launch["nnodes"]) > 1:
                if not str(verification.get("network_transport") or "").strip():
                    return False
                if int(verification.get("nnodes", -1)) != int(launch["nnodes"]):
                    return False

            expected_bindings = {
                (int(binding["rank"]), str(binding["gpu_uuid"])): binding
                for binding in participant["gpu_bindings"]
            }
            reported_bindings = verification.get("gpu_bindings")
            if not isinstance(reported_bindings, list):
                return False
            reported_keys = {
                (int(binding.get("rank", -1)), str(binding.get("gpu_uuid") or "").strip())
                for binding in reported_bindings
                if isinstance(binding, dict)
            }
            if reported_keys != set(expected_bindings):
                return False

            process_evidence = verification.get("process_evidence")
            if not isinstance(process_evidence, list) or len(process_evidence) != len(expected_bindings):
                return False
            evidence_keys = set()
            for item in process_evidence:
                if not isinstance(item, dict):
                    return False
                rank = int(item.get("rank", -1))
                gpu_binding = item.get("gpu_binding")
                probe = item.get("probe")
                if not isinstance(gpu_binding, dict) or not isinstance(probe, dict):
                    return False
                if int(launch["nnodes"]) > 1 and str(item.get("network_transport") or probe.get("network_transport") or "").strip().upper() == "IB":
                    rdma_devices = item.get("rdma_devices")
                    verified_rdma_devices = item.get("verified_rdma_devices")
                    if (
                        not isinstance(rdma_devices, list)
                        or not rdma_devices
                        or not all(isinstance(device, str) and device.strip() for device in rdma_devices)
                        or not isinstance(verified_rdma_devices, list)
                        or sorted(set(verified_rdma_devices)) != sorted(set(rdma_devices))
                    ):
                        return False
                    hca_selections = item.get("hca_selections")
                    verified_hca_selections = item.get("verified_hca_selections")
                    if (
                        not isinstance(hca_selections, list)
                        or not hca_selections
                        or not isinstance(verified_hca_selections, list)
                        or verified_hca_selections != hca_selections
                    ):
                        return False
                    for selection in hca_selections:
                        if (
                            not isinstance(selection, dict)
                            or not str(selection.get("device") or "").strip()
                            or not isinstance(selection.get("port"), int)
                            or selection.get("port") < 1
                            or str(selection.get("transport") or "").strip().upper() != "IB"
                        ):
                            return False
                    gpu_nic_locality = item.get("gpu_nic_locality")
                    if not isinstance(gpu_nic_locality, dict):
                        return False
                    if str(gpu_nic_locality.get("rdma_device") or "").strip() not in {
                        str(device).strip() for device in rdma_devices
                    }:
                        return False
                    locality_port = gpu_nic_locality.get("rdma_port")
                    if not isinstance(locality_port, int) or not any(
                        str(selection.get("device") or "").strip() == str(gpu_nic_locality.get("rdma_device") or "").strip()
                        and selection.get("port") == locality_port
                        for selection in verified_hca_selections
                        if isinstance(selection, dict)
                    ):
                        return False
                planned_path = gpu_binding.get("planned_physical_path")
                if isinstance(planned_path, dict) and (
                    int(launch["nnodes"]) > 1
                    and str(item.get("network_transport") or probe.get("network_transport") or "").strip().upper() == "IB"
                ):
                    try:
                        NvidiaRuntime.reconcile_planned_physical_path(
                            planned_path,
                            {
                                "gpu_nic_locality": item.get("gpu_nic_locality"),
                                "verified_hca_selections": item.get("verified_hca_selections"),
                            },
                        )
                    except NvidiaRuntimeError as error:
                        gpu_uuid_for_quarantine = str(gpu_binding.get("gpu_uuid") or "").strip()
                        self._quarantine_allocation_gpu_for_path_failure(
                            str(row["allocation_id"]),
                            gpu_uuid_for_quarantine,
                            reason=f"distributed physical path reconciliation failed: {error}",
                            evidence={
                                "failure_class": "planned_actual_physical_path_mismatch",
                                "attempt_id": attempt_id,
                                "worker_id": worker_id,
                                "gpu_uuid": gpu_uuid_for_quarantine,
                                "planned_physical_path": planned_path,
                                "actual_gpu_nic_locality": item.get("gpu_nic_locality"),
                                "verified_hca_selections": item.get("verified_hca_selections"),
                            },
                        )
                        return False
                gpu_uuid = str(gpu_binding.get("gpu_uuid") or "").strip()
                key = (rank, gpu_uuid)
                if key in evidence_keys or key not in expected_bindings:
                    return False
                if (
                    int(probe.get("rank", -1)) != rank
                    or int(probe.get("world_size", -1)) != int(launch["world_size"])
                    or probe.get("backend") != "nccl"
                    or probe.get("collective") != "all_reduce"
                    or probe.get("verified_on_gpu") is not True
                    or str(probe.get("gpu_uuid") or "").strip() != gpu_uuid
                    or (
                        int(launch["nnodes"]) > 1
                        and (
                            int(probe.get("nnodes", -1)) != int(launch["nnodes"])
                            or not str(probe.get("network_transport") or "").strip()
                        )
                    )
                ):
                    return False
                evidence_keys.add(key)
            if evidence_keys != set(expected_bindings):
                return False

            serialized = json.dumps(verification, ensure_ascii=False, sort_keys=True)
            with self._connect() as connection:
                connection.execute(
                    """UPDATE compute_execution_participants
                       SET verification=?,status='running',heartbeat_at=?,last_error=''
                       WHERE attempt_id=? AND generation=? AND worker_id=?
                         AND status IN ('bound','launching','active','running')""",
                    (serialized, now, attempt_id, generation, worker_id),
                )
                connection.execute(
                    """UPDATE compute_tasks SET lease_until=?,updated_at=?
                       WHERE task_id=? AND status='leased' AND lease_until > ?""",
                    (now + self.lease_seconds, now, row["task_id"], now),
                )
                connection.commit()
        return True


    def converge_fabric_execution(
        self, *, attempt_id: str, generation: int, worker_id: str, lease_token: str,
    ) -> Dict[str, Any]:
        """Converge an execution attempt only after every participant has verified.

        This closes the distributed execution attempt, not the business task.
        The business result still requires the separate authoritative completion path.
        """
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            with self._connect() as connection:
                attempt = connection.execute(
                    "SELECT * FROM compute_execution_attempts WHERE attempt_id=? AND generation=?",
                    (attempt_id, generation),
                ).fetchone()
                participant = connection.execute(
                    """SELECT p.worker_id,p.status,p.verification
                       FROM compute_execution_participants p
                       JOIN compute_tasks t ON t.task_id=p.task_id
                       WHERE p.attempt_id=? AND p.generation=? AND p.worker_id=?
                         AND t.status='leased' AND t.lease_until > ?""",
                    (attempt_id, generation, worker_id, now),
                ).fetchone()
                if not attempt or not participant or attempt["lease_token_digest"] != lease_digest:
                    return {"converged": False, "reason": "execution_identity_rejected"}
                if attempt["status"] == "completed" and attempt["authoritative_acceptance"] == "accepted":
                    return {"converged": True, "status": "completed", "already_completed": True}
                if attempt["status"] != "leased" or participant["status"] not in {"running", "completed"}:
                    return {"converged": False, "reason": "participant_not_running"}
                participants = connection.execute(
                    """SELECT worker_id,status,verification
                       FROM compute_execution_participants
                       WHERE attempt_id=? AND generation=?
                       ORDER BY rank""",
                    (attempt_id, generation),
                ).fetchall()
                if not participants or any(
                    row["status"] != "running" or not row["verification"]
                    for row in participants
                ):
                    return {
                        "converged": False,
                        "reason": "awaiting_all_participant_verifications",
                        "verified_participants": sum(1 for row in participants if row["verification"]),
                        "participant_count": len(participants),
                    }

                try:
                    launch = self.fabric_launch_plan(
                        attempt_id,
                        str(attempt["rendezvous_endpoint"] or "").strip(),
                    )
                    aggregated_process_evidence = []
                    for row in participants:
                        verification = json.loads(row["verification"])
                        process_evidence = verification.get("process_evidence")
                        if not isinstance(process_evidence, list):
                            raise NvidiaRuntimeError(
                                f"participant {row['worker_id']} has no process evidence for path reconciliation"
                            )
                        aggregated_process_evidence.extend(
                            item for item in process_evidence if isinstance(item, dict)
                        )
                    path_reconciliation = NvidiaRuntime.reconcile_distributed_network_paths(
                        aggregated_process_evidence,
                        world_size=int(launch["world_size"]),
                        nnodes=int(launch["nnodes"]),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError, NvidiaRuntimeError) as error:
                    return {
                        "converged": False,
                        "reason": "network_path_reconciliation_failed",
                        "detail": str(error)[:4000],
                    }

                updated = connection.execute(
                    """UPDATE compute_execution_attempts
                       SET status='completed',finished_at=?,authoritative_acceptance='accepted'
                       WHERE attempt_id=? AND generation=? AND status='leased'
                         AND lease_token_digest=?""",
                    (now, attempt_id, generation, lease_digest),
                )
                if updated.rowcount != 1:
                    row = connection.execute(
                        "SELECT status,authoritative_acceptance FROM compute_execution_attempts WHERE attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                    if row and row["status"] == "completed" and row["authoritative_acceptance"] == "accepted":
                        return {"converged": True, "status": "completed", "already_completed": True}
                    return {"converged": False, "reason": "concurrent_convergence"}
                connection.execute(
                    """UPDATE compute_execution_participants
                       SET status='completed',finished_at=?,heartbeat_at=?
                       WHERE attempt_id=? AND generation=? AND status='running'""",
                    (now, now, attempt_id, generation),
                )
                evidence = [
                    {
                        "worker_id": row["worker_id"],
                        "verification": json.loads(row["verification"]),
                    }
                    for row in participants
                ]
                connection.execute(
                    """UPDATE compute_execution_attempts
                       SET verification=?
                       WHERE attempt_id=? AND generation=? AND status='completed'""",
                    (json.dumps({"participants": evidence}, ensure_ascii=False, sort_keys=True), attempt_id, generation),
                )
                connection.commit()
        return {"converged": True, "status": "completed", "already_completed": False}

    def fabric_launch_plan_for_worker(
        self, *, attempt_id: str, generation: int, worker_id: str,
        lease_token: str, rendezvous_endpoint: str,
    ) -> Dict[str, Any]:
        durable_endpoint = self._bind_rendezvous_endpoint(
            attempt_id, generation, lease_token, rendezvous_endpoint
        )
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM compute_execution_participants p
                   JOIN compute_execution_attempts a ON a.attempt_id=p.attempt_id
                   WHERE p.attempt_id=? AND p.generation=? AND p.worker_id=?
                     AND p.status IN ('bound','active','launching','running')
                     AND a.status='leased' AND a.lease_token_digest=?
                     AND EXISTS (
                         SELECT 1 FROM compute_tasks t
                         WHERE t.task_id=p.task_id AND t.status='leased' AND t.lease_until > ?
                     )""",
                (attempt_id, generation, worker_id, lease_digest, time.time()),
            ).fetchone()
        if not row:
            raise ValueError("worker is not an active participant for this execution attempt")
        return self.fabric_launch_plan(attempt_id, durable_endpoint)

    def heartbeat_execution_participant(
        self,
        *,
        attempt_id: str,
        generation: int,
        worker_id: str,
        lease_token: str,
    ) -> bool:
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            with self._connect() as connection:
                authorized = connection.execute(
                    """SELECT 1
                       FROM compute_execution_participants p
                       JOIN compute_execution_attempts a
                         ON a.attempt_id=p.attempt_id
                        AND a.generation=p.generation
                       WHERE p.attempt_id=? AND p.generation=? AND p.worker_id=?
                         AND p.status IN ('bound','active','running')
                         AND a.status='leased'
                         AND a.lease_token_digest=?
                         AND EXISTS (
                             SELECT 1 FROM compute_tasks t
                             WHERE t.task_id=p.task_id
                               AND t.status='leased'
                               AND t.lease_until > ?
                         )""",
                    (attempt_id, generation, worker_id, lease_digest, now),
                ).fetchone()
                if not authorized:
                    return False

            worker = self.pool.worker(worker_id)
            if worker is None:
                return False
            if not self.pool.heartbeat(worker_id, int(worker["current_load"])):
                return False
            with self._connect() as connection:
                cursor = connection.execute(
                    """UPDATE compute_execution_participants
                       SET heartbeat_at=?,
                           status=CASE WHEN status='running' THEN 'running' ELSE 'active' END,
                           last_error=''
                       WHERE attempt_id=? AND generation=? AND worker_id=?
                       AND status IN ('bound','active','running')
                       AND EXISTS (
                           SELECT 1 FROM compute_execution_attempts a
                           WHERE a.attempt_id=compute_execution_participants.attempt_id
                           AND a.task_id=compute_execution_participants.task_id
                           AND a.generation=compute_execution_participants.generation
                           AND a.status='leased'
                           AND a.lease_token_digest=?
                           AND EXISTS (
                               SELECT 1 FROM compute_tasks t
                               WHERE t.task_id=compute_execution_participants.task_id
                               AND t.status='leased' AND t.lease_until > ?
                           )
                       )""",
                    (now, attempt_id, generation, worker_id, lease_digest, now),
                )
                if cursor.rowcount == 1:
                    connection.execute(
                        """UPDATE compute_tasks
                           SET lease_until=?,updated_at=?
                           WHERE task_id=(SELECT task_id FROM compute_execution_participants
                                          WHERE attempt_id=? AND generation=? AND worker_id=?)
                             AND status='leased' AND lease_until > ?""",
                        (now + self.lease_seconds, now, attempt_id, generation, worker_id, now),
                    )
                connection.commit()
                return cursor.rowcount == 1

    def _valid_lease(self, connection: sqlite3.Connection, worker_id: str, task_id: str, lease_token: str) -> bool:
        row = connection.execute("SELECT status,worker_id,lease_token,lease_until FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()
        return bool(row and row["status"] == "leased" and row["worker_id"] == worker_id and row["lease_token"] and hmac.compare_digest(row["lease_token"], lease_token) and row["lease_until"] > time.time())

    def complete(self, worker_id: str, task_id: str, lease_token: str, result: Dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        result_digest = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        with self._lock:
            with self._connect() as connection:
                row = connection.execute("SELECT status,completed_worker_id,completed_lease_digest,completed_result_digest,attempt_id FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()
                if row and row["status"] == "completed":
                    return bool(row["completed_worker_id"] == worker_id and row["completed_lease_digest"] == lease_digest and row["completed_result_digest"] == result_digest)
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    return False
                now = time.time()
                connection.execute("UPDATE compute_tasks SET status='completed',result=?,error='',lease_token=NULL,lease_until=NULL,completed_worker_id=?,completed_lease_digest=?,completed_result_digest=?,updated_at=? WHERE task_id=?", (json.dumps(result, ensure_ascii=False), worker_id, lease_digest, result_digest, now, task_id))
                attempt_id = row["attempt_id"] if row else None
                attempt = None
                if attempt_id:
                    attempt = connection.execute("SELECT * FROM compute_execution_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
                    connection.execute("UPDATE compute_execution_attempts SET status='completed',finished_at=?,authoritative_acceptance=CASE WHEN authoritative_acceptance='accepted' THEN 'accepted' ELSE 'pending' END WHERE attempt_id=?", (now, attempt_id))
                connection.commit()
            if attempt:
                self._set_execution_participant_status(str(attempt["attempt_id"]), "completed")
                self._release_physical_allocation(dict(attempt), "execution completed")
            self.pool.release_task_slot(worker_id)
        return True

    def release(self, worker_id: str, task_id: str, lease_token: str, error: str = "") -> bool:
        with self._lock:
            with self._connect() as connection:
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    return False
                now = time.time()
                row = connection.execute("SELECT attempt_id FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()
                attempt = None
                if row and row["attempt_id"]:
                    attempt = connection.execute("SELECT * FROM compute_execution_attempts WHERE attempt_id=?", (row["attempt_id"],)).fetchone()
                connection.execute("UPDATE compute_tasks SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,error=?,updated_at=? WHERE task_id=?", (str(error)[:4000], now, task_id))
                if row and row["attempt_id"]:
                    connection.execute("UPDATE compute_execution_attempts SET status='released',finished_at=?,error=? WHERE attempt_id=?", (now, str(error)[:4000], row["attempt_id"]))
                connection.commit()
            if attempt:
                self._set_execution_participant_status(str(attempt["attempt_id"]), "released", error)
                self._release_physical_allocation(dict(attempt), "execution released")
            self.pool.release_task_slot(worker_id)
        return True

    def reconcile_fabric(self, participant_timeout_seconds: float | None = None) -> Dict[str, int]:
        """Fail and requeue fabric attempts whose required participant set is no longer healthy.

        This is deliberately conservative: one missing/stale participant invalidates
        the whole distributed attempt. The exact attempt lease and allocation are
        then retired before the task is returned to the durable queue.
        """
        timeout = float(participant_timeout_seconds if participant_timeout_seconds is not None else max(1, self.lease_seconds))
        if timeout <= 0:
            raise ValueError("participant_timeout_seconds must be positive")
        now = time.time()
        stale_attempts: list[Dict[str, Any]] = []
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT a.*, t.lease_until
                       FROM compute_execution_attempts a
                       JOIN compute_tasks t ON t.attempt_id=a.attempt_id
                       WHERE a.status='leased' AND t.status='leased'"""
                ).fetchall()
                for attempt_row in rows:
                    attempt = dict(attempt_row)
                    participants = connection.execute(
                        """SELECT p.worker_id,p.status,p.heartbeat_at,w.last_heartbeat
                           FROM compute_execution_participants p
                           LEFT JOIN compute_workers w ON w.worker_id=p.worker_id
                           WHERE p.attempt_id=? AND p.generation=?
                           ORDER BY p.rank""",
                        (attempt["attempt_id"], attempt["generation"]),
                    ).fetchall()
                    if not participants:
                        continue
                    missing = any(
                        str(p["status"]) not in {"bound", "active", "launching", "running"}
                        or float(p["heartbeat_at"]) + timeout <= now
                        or p["last_heartbeat"] is None
                        or float(p["last_heartbeat"]) + timeout <= now

                        for p in participants
                    )
                    if missing:
                        stale_attempts.append(attempt)
                if not stale_attempts:
                    return {"reconciled": 0, "requeued": 0}
                reconciled_attempts = []
                for attempt in stale_attempts:
                    task_id = str(attempt["task_id"])
                    updated = connection.execute(
                        """UPDATE compute_tasks
                           SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,
                               error=?,updated_at=?
                           WHERE task_id=? AND status='leased' AND attempt_id=? AND generation=?""",
                        ("fabric participant lost", now, task_id, attempt["attempt_id"], attempt["generation"]),
                    )
                    if updated.rowcount != 1:
                        continue
                    attempt_updated = connection.execute(
                        """UPDATE compute_execution_attempts
                           SET status='failed',finished_at=?,error=?,authoritative_acceptance='rejected'
                           WHERE attempt_id=? AND generation=? AND status='leased'""",
                        (now, "fabric participant lost", attempt["attempt_id"], attempt["generation"]),
                    )
                    if attempt_updated.rowcount != 1:
                        connection.rollback()
                        continue
                    connection.execute(
                        """UPDATE compute_execution_participants
                           SET status='failed',last_error=?,heartbeat_at=?
                           WHERE attempt_id=? AND generation=? AND status IN ('bound','active','launching','running')""",
                        ("fabric participant lost", now, attempt["attempt_id"], attempt["generation"]),
                    )
                    reconciled_attempts.append(attempt)
                connection.commit()
            for attempt in reconciled_attempts:
                self._release_physical_allocation(attempt, "fabric participant lost")
                if attempt.get("worker_id") and not str(attempt["worker_id"]).startswith("fabric:"):
                    self.pool.release_task_slot(str(attempt["worker_id"]))
        return {"reconciled": len(reconciled_attempts), "requeued": len(reconciled_attempts)}

    def recover_expired_tasks(self) -> int:
        now = time.time()
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT task_id,worker_id,attempt_id FROM compute_tasks "
                    "WHERE status='leased' AND lease_until <= ?",
                    (now,),
                ).fetchall()
                if not rows:
                    return 0

                attempts = []
                for row in rows:
                    if not row["attempt_id"]:
                        attempts.append(None)
                        continue
                    attempt = connection.execute(
                        "SELECT * FROM compute_execution_attempts WHERE attempt_id=?",
                        (row["attempt_id"],),
                    ).fetchone()
                    attempts.append(dict(attempt) if attempt else None)

                connection.execute(
                    "UPDATE compute_tasks SET status='queued',worker_id=NULL,lease_token=NULL,"
                    "lease_until=NULL,error='lease expired',updated_at=? "
                    "WHERE status='leased' AND lease_until <= ?",
                    (now, now),
                )

                for attempt in attempts:
                    if not attempt:
                        continue
                    if attempt["status"] == "completed":
                        connection.execute(
                            "UPDATE compute_execution_participants SET status='completed',"
                            "finished_at=COALESCE(finished_at,?) "
                            "WHERE attempt_id=? AND generation=? AND status NOT IN ('failed','expired')",
                            (now, attempt["attempt_id"], attempt["generation"]),
                        )
                    elif attempt["status"] == "leased":
                        connection.execute(
                            "UPDATE compute_execution_attempts SET status='expired',"
                            "finished_at=?,error='lease expired',authoritative_acceptance='rejected' "
                            "WHERE attempt_id=? AND generation=? AND status='leased'",
                            (now, attempt["attempt_id"], attempt["generation"]),
                        )
                        connection.execute(
                            "UPDATE compute_execution_participants SET status='expired',"
                            "last_error='lease expired',heartbeat_at=? "
                            "WHERE attempt_id=? AND generation=? "
                            "AND status IN ('bound','active','launching','running')",
                            (now, attempt["attempt_id"], attempt["generation"]),
                        )
                connection.commit()

            for attempt in attempts:
                if not attempt:
                    continue
                self._release_physical_allocation(attempt, "execution lease expired")
                if attempt.get("worker_id") and not str(attempt["worker_id"]).startswith("fabric:"):
                    self.pool.release_task_slot(str(attempt["worker_id"]))
            return len(rows)

    def health(self) -> Dict[str, Any]:
        with self._lock:
            self.pool.reap_stale_workers(); self.recover_expired_tasks(); self.reconcile_fabric()
            with self._connect() as connection:
                queued = connection.execute("SELECT COUNT(*) FROM compute_tasks WHERE status='queued'").fetchone()[0]
                leased = connection.execute("SELECT COUNT(*) FROM compute_tasks WHERE status='leased'").fetchone()[0]
                completed = connection.execute("SELECT COUNT(*) FROM compute_tasks WHERE status='completed'").fetchone()[0]
            capacity = self.pool.capacity_snapshot()
            return {"ok": True, "free_only": True, "queued": queued, "leased": leased, "completed": completed, "capacity": capacity}


class _Handler(BaseHTTPRequestHandler):
    server: "ComputeCoordinatorServer"

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.coordinator.auth_token}"
        return hmac.compare_digest(supplied, expected)

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorized(): self._send(401, {"error": "unauthorized"}); return
        if self.path == "/health": self._send(200, self.server.coordinator.health()); return
        if self.path.startswith("/work/status/"):
            task_id = self.path.rsplit("/", 1)[-1]; task = self.server.coordinator.task(task_id); self._send(200 if task else 404, task or {"error": "task not found"}); return
        if self.path.startswith("/work/checkpoints/"):
            task_id = self.path.rsplit("/", 1)[-1]; self._send(200, self.server.coordinator.checkpoint_results(task_id)); return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized(): self._send(401, {"error": "unauthorized"}); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000: self._send(413, {"error": "request too large"}); return
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(body, dict): raise ValueError("request body must be an object")
            if self.path == "/workers/register":
                worker_id = str(body["worker_id"])
                identity = WorkerIdentity(
                    worker_id, str(body["hostname"]), str(body["architecture"]), int(body["cpu_count"]), int(body["memory_mb"]),
                    tuple(str(x) for x in body.get("capabilities", ["lead-processing"])),
                    ComputeCoordinator._gpu_resources_from_payload(body.get("gpu_resources"), worker_id),
                    body.get("driver_version"), body.get("cuda_version"), body.get("nccl_version"),
                    tuple(str(x) for x in body.get("nic_names", ())), str(body.get("gpu_discovery_state", "not_probed")),
                    str(body.get("gpu_discovery_error", "")),
                )
                self._send(200, self.server.coordinator.register_worker(identity))
            elif self.path == "/workers/heartbeat":
                self._send(200, {"ok": self.server.coordinator.heartbeat(str(body["worker_id"]), int(body.get("current_load", 0)))})
            elif self.path == "/fabric/assignments":
                self._send(200, {"assignments": self.server.coordinator.fabric_assignments(str(body["worker_id"]))})
            elif self.path == "/fabric/heartbeat":
                ok = self.server.coordinator.heartbeat_execution_participant(
                    attempt_id=str(body["attempt_id"]), generation=int(body["generation"]),
                    worker_id=str(body["worker_id"]), lease_token=str(body["lease_token"])
                )
                self._send(200 if ok else 409, {"ok": ok})
            elif self.path == "/fabric/state":
                ok = self.server.coordinator.execution_participant_state(
                    attempt_id=str(body["attempt_id"]), generation=int(body["generation"]),
                    worker_id=str(body["worker_id"]), lease_token=str(body["lease_token"]),
                    status=str(body["status"]), error=str(body.get("error", ""))
                )
                self._send(200 if ok else 409, {"ok": ok})
            elif self.path == "/fabric/launch-plan":
                plan = self.server.coordinator.fabric_launch_plan_for_worker(
                    attempt_id=str(body["attempt_id"]), generation=int(body["generation"]),
                    worker_id=str(body["worker_id"]), lease_token=str(body["lease_token"]),
                    rendezvous_endpoint=str(body["rendezvous_endpoint"])
                )
                self._send(200, plan)
            elif self.path == "/fabric/converge":
                result = self.server.coordinator.converge_fabric_execution(
                    attempt_id=str(body["attempt_id"]), generation=int(body["generation"]),
                    worker_id=str(body["worker_id"]), lease_token=str(body["lease_token"])
                )
                self._send(200 if result.get("converged") else 409, result)
            elif self.path == "/fabric/verification":
                ok = self.server.coordinator.record_execution_verification(
                    attempt_id=str(body["attempt_id"]), generation=int(body["generation"]),
                    worker_id=str(body["worker_id"]), lease_token=str(body["lease_token"]),
                    verification=body["verification"]
                )
                self._send(200 if ok else 409, {"ok": ok})
            elif self.path == "/work/enqueue":
                payload = body.get("payload")
                if not isinstance(payload, dict): raise ValueError("payload must be an object")
                task_id = body.get("task_id")
                if task_id is not None and not isinstance(task_id, str): raise ValueError("task_id must be a string")
                self._send(201, {"task_id": self.server.coordinator.enqueue(payload, task_id=task_id)})
            elif self.path == "/work/claim":
                item = self.server.coordinator.claim(str(body["worker_id"])); self._send(200, item or {"task": None})
            elif self.path == "/work/checkpoint":
                result = self.server.coordinator.checkpoint_lead_prepare(
                    str(body["worker_id"]), str(body["task_id"]), str(body["lease_token"]), body["items"]
                ); self._send(200, result)
            elif self.path == "/work/complete":
                ok = self.server.coordinator.complete(str(body["worker_id"]), str(body["task_id"]), str(body["lease_token"]), body["result"]); self._send(200 if ok else 409, {"completed": ok})
            elif self.path == "/work/release":
                ok = self.server.coordinator.release(str(body["worker_id"]), str(body["task_id"]), str(body["lease_token"]), str(body.get("error", ""))); self._send(200 if ok else 409, {"released": ok})
            else: self._send(404, {"error": "not found"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._send(400, {"error": str(error)})
        except sqlite3.IntegrityError as error:
            self._send(409, {"error": str(error)})
        except Exception as error:
            self._send(500, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        return


class ComputeCoordinatorServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, coordinator: ComputeCoordinator, host: str = "127.0.0.1", port: int = 8787):
        self.coordinator = coordinator
        super().__init__((host, port), _Handler)


def coordinator_from_environment() -> ComputeCoordinator:
    token = os.environ.get("THORIO_COMPUTE_AUTH_TOKEN", "")
    if not token: raise RuntimeError("THORIO_COMPUTE_AUTH_TOKEN is required")
    return ComputeCoordinator(os.environ.get("THORIO_COMPUTE_DB", os.environ.get("LEAD_ENGINE_DATA_DIR", "data") + "/coordinator.sqlite3"), token, int(os.environ.get("THORIO_COMPUTE_LEASE_SECONDS", "300")))


def serve_from_environment() -> None:
    coordinator = coordinator_from_environment(); host = os.environ.get("THORIO_COMPUTE_BIND_HOST", "127.0.0.1"); port = int(os.environ.get("THORIO_COMPUTE_PORT", "8787")); server = ComputeCoordinatorServer(coordinator, host, port)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        cert = os.environ.get("THORIO_COMPUTE_TLS_CERT", ""); key = os.environ.get("THORIO_COMPUTE_TLS_KEY", "")
        if not cert or not key: server.server_close(); raise RuntimeError("non-local coordinator binding requires THORIO_COMPUTE_TLS_CERT and THORIO_COMPUTE_TLS_KEY")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(certfile=cert, keyfile=key); server.socket = context.wrap_socket(server.socket, server_side=True)
    try: server.serve_forever(poll_interval=1.0)
    finally: server.server_close()


if __name__ == "__main__":
    serve_from_environment()
