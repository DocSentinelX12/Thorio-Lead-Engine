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

from .compute_pool import ComputePool, WorkerIdentity


class ComputeCoordinator:
    def __init__(self, db_path: str, auth_token: str, lease_seconds: int = 300):
        if not auth_token:
            raise ValueError("auth_token is required")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.db_path = db_path
        self.auth_token = auth_token
        self.pool = ComputePool(db_path, lease_seconds=lease_seconds)
        self.lease_seconds = lease_seconds
        self._lock = threading.RLock()
        self._initialize_tasks()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
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
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_tasks_status ON compute_tasks(status, created_at)")
            connection.commit()

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
                existing = connection.execute(
                    "SELECT payload,status FROM compute_tasks WHERE task_id=?",
                    (resolved_id,),
                ).fetchone()
                if existing:
                    if json.dumps(json.loads(existing["payload"]), ensure_ascii=False, sort_keys=True) != serialized:
                        raise ValueError(f"task_id already exists with a different payload: {resolved_id}")
                    return resolved_id
                connection.execute(
                    "INSERT INTO compute_tasks(task_id,payload,created_at,updated_at) VALUES(?,?,?,?)",
                    (resolved_id, serialized, now, now),
                )
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

    def register_worker(self, identity: WorkerIdentity) -> Dict[str, Any]:
        return self.pool.register(identity)

    def heartbeat(self, worker_id: str, current_load: int = 0) -> bool:
        return self.pool.heartbeat(worker_id, current_load)

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
                    rows = connection.execute(
                        "SELECT task_id,payload FROM compute_tasks "
                        "WHERE status='queued' ORDER BY created_at,task_id LIMIT 100 OFFSET ?",
                        (offset,),
                    ).fetchall()
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
                updated = connection.execute(
                    "UPDATE compute_tasks SET status='leased',worker_id=?,lease_token=?,lease_until=?,attempts=attempts+1,attempt_id=?,generation=?,updated_at=? WHERE task_id=? AND status='queued'",
                    (worker_id, lease_token, now + self.lease_seconds, attempt_id, generation, now, task_id),
                )
                if updated.rowcount != 1:
                    connection.rollback()
                    self.pool.release_task_slot(worker_id)
                    return None
                lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
                connection.execute(
                    "INSERT INTO compute_execution_attempts(attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at) VALUES(?,?,?,?,?,?,?)",
                    (attempt_id, task_id, generation, worker_id, "leased", lease_digest, now),
                )
                connection.commit()
            return {"task_id": task_id, "attempt_id": attempt_id, "generation": generation, "payload": json.loads(selected["payload"]), "lease_token": lease_token}


    def execution_attempt_for_allocation(self, allocation_id: str) -> Optional[Dict[str, Any]]:
        """Return the execution attempt that claims a physical allocation."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_execution_attempts WHERE allocation_id=? ORDER BY generation DESC LIMIT 1",
                (allocation_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["resource_ids"] = json.loads(item["resource_ids"] or "[]")
        item["artifact_refs"] = json.loads(item["artifact_refs"] or "[]")
        return item

    def execution_attempt(self, attempt_id: str) -> Optional[Dict[str, Any]]:
        """Return one durable execution attempt for resource reconciliation."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_execution_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["resource_ids"] = json.loads(item["resource_ids"] or "[]")
        item["artifact_refs"] = json.loads(item["artifact_refs"] or "[]")
        return item

    def bind_physical_allocation(
        self,
        *,
        task_id: str,
        attempt_id: str,
        generation: int,
        allocation_id: str,
        provider_id: str,
        domain_id: str,
        resource_ids: list[str] | tuple[str, ...],
        lease_token: str,
    ) -> bool:
        """Durably attach one physical allocation to one exact leased attempt.

        The coordinator records the binding but does not own physical resources.
        The resource inventory remains authoritative for physical allocation.
        """
        if not task_id.strip() or not attempt_id.strip() or not allocation_id.strip():
            raise ValueError("task, attempt, and allocation identities are required")
        if generation < 1 or not provider_id.strip() or not domain_id.strip() or not resource_ids:
            raise ValueError("complete physical allocation metadata is required")
        lease_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        serialized_ids = json.dumps(tuple(dict.fromkeys(str(item) for item in resource_ids)), ensure_ascii=False)
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT a.status,a.task_id,a.generation,a.worker_id,a.lease_token_digest,
                              a.allocation_id,a.provider_id,a.domain_id,a.resource_ids
                       FROM compute_execution_attempts a
                       JOIN compute_tasks t ON t.attempt_id=a.attempt_id
                       WHERE a.attempt_id=? AND a.task_id=?""",
                    (attempt_id, task_id),
                ).fetchone()
                if not row or row["generation"] != generation or row["status"] != "leased":
                    return False
                if row["lease_token_digest"] != lease_digest:
                    return False
                if row["allocation_id"]:
                    return bool(
                        row["allocation_id"] == allocation_id
                        and row["provider_id"] == provider_id
                        and row["domain_id"] == domain_id
                        and row["resource_ids"] == serialized_ids
                    )
                cursor = connection.execute(
                    """UPDATE compute_execution_attempts
                       SET allocation_id=?,provider_id=?,domain_id=?,resource_ids=?
                       WHERE attempt_id=? AND task_id=? AND generation=?
                         AND status='leased' AND allocation_id IS NULL""",
                    (allocation_id, provider_id, domain_id, serialized_ids, attempt_id, task_id, generation),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return False
                connection.commit()
                return True

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
                row = connection.execute(
                    "SELECT status,completed_worker_id,completed_lease_digest,completed_result_digest,attempt_id FROM compute_tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if row and row["status"] == "completed":
                    return bool(
                        row["completed_worker_id"] == worker_id
                        and row["completed_lease_digest"] == lease_digest
                        and row["completed_result_digest"] == result_digest
                    )
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    return False
                now = time.time()
                connection.execute(
                    "UPDATE compute_tasks SET status='completed',result=?,error='',lease_token=NULL,lease_until=NULL,completed_worker_id=?,completed_lease_digest=?,completed_result_digest=?,updated_at=? WHERE task_id=?",
                    (json.dumps(result, ensure_ascii=False), worker_id, lease_digest, result_digest, now, task_id),
                )
                attempt_id = row["attempt_id"] if row else None
                if attempt_id:
                    connection.execute(
                        "UPDATE compute_execution_attempts SET status='completed',finished_at=?,authoritative_acceptance='pending' WHERE attempt_id=?",
                        (now, attempt_id),
                    )
                connection.commit()
            self.pool.release_task_slot(worker_id)
        return True

    def release(self, worker_id: str, task_id: str, lease_token: str, error: str = "") -> bool:
        with self._lock:
            with self._connect() as connection:
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    return False
                now = time.time()
                row = connection.execute("SELECT attempt_id FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()
                connection.execute(
                    "UPDATE compute_tasks SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,error=?,updated_at=? WHERE task_id=?",
                    (str(error)[:4000], now, task_id),
                )
                if row and row["attempt_id"]:
                    connection.execute(
                        "UPDATE compute_execution_attempts SET status='released',finished_at=?,error=? WHERE attempt_id=?",
                        (now, str(error)[:4000], row["attempt_id"]),
                    )
                connection.commit()
            self.pool.release_task_slot(worker_id)
        return True

    def recover_expired_tasks(self) -> int:
        now = time.time()
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT task_id,worker_id,attempt_id FROM compute_tasks WHERE status='leased' AND lease_until <= ?",
                    (now,),
                ).fetchall()
                if not rows:
                    return 0
                connection.execute(
                    "UPDATE compute_tasks SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,error='lease expired',updated_at=? WHERE status='leased' AND lease_until <= ?",
                    (now, now),
                )
                for row in rows:
                    if row["attempt_id"]:
                        connection.execute(
                            "UPDATE compute_execution_attempts SET status='expired',finished_at=?,error='lease expired' WHERE attempt_id=?",
                            (now, row["attempt_id"]),
                        )
                connection.commit()
            for row in rows:
                if row["worker_id"]:
                    self.pool.release_task_slot(row["worker_id"])
            return len(rows)

    def health(self) -> Dict[str, Any]:
        with self._lock:
            self.pool.reap_stale_workers()
            self.recover_expired_tasks()
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path == "/health":
            self._send(200, self.server.coordinator.health())
            return
        if self.path.startswith("/work/status/"):
            task_id = self.path.rsplit("/", 1)[-1]
            task = self.server.coordinator.task(task_id)
            self._send(200 if task else 404, task or {"error": "task not found"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                self._send(413, {"error": "request too large"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            if self.path == "/workers/register":
                identity = WorkerIdentity(str(body["worker_id"]), str(body["hostname"]), str(body["architecture"]), int(body["cpu_count"]), int(body["memory_mb"]), tuple(str(x) for x in body.get("capabilities", ["lead-processing"])))
                self._send(200, self.server.coordinator.register_worker(identity))
            elif self.path == "/workers/heartbeat":
                self._send(200, {"ok": self.server.coordinator.heartbeat(str(body["worker_id"]), int(body.get("current_load", 0)))})
            elif self.path == "/work/enqueue":
                payload = body.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                task_id = body.get("task_id")
                if task_id is not None and not isinstance(task_id, str):
                    raise ValueError("task_id must be a string")
                created_id = self.server.coordinator.enqueue(payload, task_id=task_id)
                self._send(201, {"task_id": created_id})
            elif self.path == "/work/claim":
                item = self.server.coordinator.claim(str(body["worker_id"]))
                self._send(200, item or {"task": None})
            elif self.path == "/work/complete":
                ok = self.server.coordinator.complete(str(body["worker_id"]), str(body["task_id"]), str(body["lease_token"]), body["result"])
                self._send(200 if ok else 409, {"completed": ok})
            elif self.path == "/work/release":
                ok = self.server.coordinator.release(str(body["worker_id"]), str(body["task_id"]), str(body["lease_token"]), str(body.get("error", "")))
                self._send(200 if ok else 409, {"released": ok})
            else:
                self._send(404, {"error": "not found"})
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
    if not token:
        raise RuntimeError("THORIO_COMPUTE_AUTH_TOKEN is required")
    return ComputeCoordinator(
        os.environ.get("THORIO_COMPUTE_DB", os.environ.get("LEAD_ENGINE_DATA_DIR", "data") + "/coordinator.sqlite3"),
        token,
        int(os.environ.get("THORIO_COMPUTE_LEASE_SECONDS", "300")),
    )


def serve_from_environment() -> None:
    coordinator = coordinator_from_environment()
    host = os.environ.get("THORIO_COMPUTE_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("THORIO_COMPUTE_PORT", "8787"))
    server = ComputeCoordinatorServer(coordinator, host, port)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        cert = os.environ.get("THORIO_COMPUTE_TLS_CERT", "")
        key = os.environ.get("THORIO_COMPUTE_TLS_KEY", "")
        if not cert or not key:
            server.server_close()
            raise RuntimeError("non-local coordinator binding requires THORIO_COMPUTE_TLS_CERT and THORIO_COMPUTE_TLS_KEY")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert, keyfile=key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    try:
        server.serve_forever(poll_interval=1.0)
    finally:
        server.server_close()


if __name__ == "__main__":
    serve_from_environment()
