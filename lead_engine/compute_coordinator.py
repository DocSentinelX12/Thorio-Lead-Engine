"""Authenticated free compute coordinator for remote lead-processing workers.

The coordinator is the only component that owns the shared task state. Remote
workers never open the coordinator SQLite database directly. The service uses
only the Python standard library and an operator-provided bearer token.
"""
from __future__ import annotations

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
        self._lock = threading.Lock()
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
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_compute_tasks_status ON compute_tasks(status, created_at)")
            connection.commit()

    def enqueue(self, payload: Dict[str, Any], task_id: Optional[str] = None) -> str:
        if not isinstance(payload, dict):
            raise ValueError("task payload must be an object")
        resolved_id = task_id or str(uuid.uuid4())
        if not isinstance(resolved_id, str) or not resolved_id.strip():
            raise ValueError("task_id must be a non-empty string")
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO compute_tasks(task_id,payload,created_at,updated_at) VALUES(?,?,?,?)",
                (resolved_id, json.dumps(payload, ensure_ascii=False), now, now),
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

    def claim(self, worker_id: str) -> Optional[Dict[str, Any]]:
        self.pool.reap_stale_workers()
        self.recover_expired_tasks()
        with self._lock:
            worker = self.pool.worker(worker_id)
            if not worker or worker["status"] != "ready":
                return None
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT task_id,payload FROM compute_tasks WHERE status='queued' ORDER BY created_at,task_id LIMIT 1"
                ).fetchone()
                if not row:
                    return None
                task_id = row["task_id"]
                lease_token = str(uuid.uuid4())
                now = time.time()
                updated = connection.execute(
                    "UPDATE compute_tasks SET status='leased',worker_id=?,lease_token=?,lease_until=?,updated_at=? WHERE task_id=? AND status='queued'",
                    (worker_id, lease_token, now + self.lease_seconds, now, task_id),
                )
                if updated.rowcount != 1:
                    connection.rollback()
                    return None
                connection.commit()
            return {"task_id": task_id, "payload": json.loads(row["payload"]), "lease_token": lease_token}

    def _valid_lease(self, connection: sqlite3.Connection, worker_id: str, task_id: str, lease_token: str) -> bool:
        row = connection.execute("SELECT status,worker_id,lease_token,lease_until FROM compute_tasks WHERE task_id=?", (task_id,)).fetchone()
        return bool(row and row["status"] == "leased" and row["worker_id"] == worker_id and row["lease_token"] and hmac.compare_digest(row["lease_token"], lease_token) and row["lease_until"] > time.time())

    def complete(self, worker_id: str, task_id: str, lease_token: str, result: Dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        with self._lock:
            with self._connect() as connection:
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    return False
                connection.execute(
                    "UPDATE compute_tasks SET status='completed',result=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE task_id=?",
                    (json.dumps(result, ensure_ascii=False), time.time(), task_id),
                )
                connection.commit()
        return True

    def release(self, worker_id: str, task_id: str, lease_token: str, error: str = "") -> bool:
        with self._lock:
            with self._connect() as connection:
                if not self._valid_lease(connection, worker_id, task_id, lease_token):
                    return False
                connection.execute(
                    "UPDATE compute_tasks SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,error=?,updated_at=? WHERE task_id=?",
                    (str(error)[:4000], time.time(), task_id),
                )
                connection.commit()
        return True

    def recover_expired_tasks(self) -> int:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE compute_tasks SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,error='lease expired',updated_at=? WHERE status='leased' AND lease_until <= ?",
                (now, now),
            )
            connection.commit()
            return cursor.rowcount

    def health(self) -> Dict[str, Any]:
        self.pool.reap_stale_workers()
        self.recover_expired_tasks()
        with self._connect() as connection:
            queued = connection.execute("SELECT COUNT(*) FROM compute_tasks WHERE status='queued'").fetchone()[0]
            leased = connection.execute("SELECT COUNT(*) FROM compute_tasks WHERE status='leased'").fetchone()[0]
            completed = connection.execute("SELECT COUNT(*) FROM compute_tasks WHERE status='completed'").fetchone()[0]
        return {"ok": True, "free_only": True, "queued": queued, "leased": leased, "completed": completed, "capacity": self.pool.capacity_snapshot()}


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
