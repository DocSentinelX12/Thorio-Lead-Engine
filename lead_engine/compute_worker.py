"""Free remote worker client for the shared compute coordinator."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .advanced_agent_logic import advanced_handler_registry
from .compute_pool import local_worker_identity
from .lead_pipeline import process_leads


class ComputeWorkerError(RuntimeError):
    pass


@dataclass
class ComputeWorkerClient:
    coordinator_url: str
    auth_token: str
    worker_id: str
    timeout_seconds: int = 20

    def __post_init__(self) -> None:
        self.coordinator_url = self.coordinator_url.rstrip("/")
        if not self.coordinator_url.startswith(("http://", "https://")):
            raise ValueError("coordinator_url must use HTTP or HTTPS")
        if not self.auth_token:
            raise ValueError("auth_token is required")
        if not self.worker_id:
            raise ValueError("worker_id is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def request(self, path: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        body = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.coordinator_url + path,
            data=body,
            method="GET" if body is None else "POST",
            headers={"Authorization": f"Bearer {self.auth_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ComputeWorkerError(f"coordinator HTTP {error.code}: {error.read().decode('utf-8', errors='replace')[:1000]}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ComputeWorkerError(f"coordinator unavailable: {error}") from error

    def register(self) -> Dict[str, Any]:
        identity = local_worker_identity(self.worker_id)
        advanced = list(advanced_handler_registry())
        return self.request("/workers/register", {
            "worker_id": identity.worker_id,
            "hostname": identity.hostname,
            "architecture": identity.architecture,
            "cpu_count": identity.cpu_count,
            "memory_mb": identity.memory_mb,
            "capabilities": list(identity.capabilities) + ["lead_prepare", "advanced_agent_task"] + advanced,
        })

    def heartbeat(self, current_load: int = 0) -> Dict[str, Any]:
        return self.request("/workers/heartbeat", {"worker_id": self.worker_id, "current_load": current_load})

    def claim(self) -> Optional[Dict[str, Any]]:
        result = self.request("/work/claim", {"worker_id": self.worker_id})
        return result if result.get("task_id") else None

    def status(self, task_id: str) -> Dict[str, Any]:
        return self.request(f"/work/status/{task_id}")

    def enqueue(self, payload: Mapping[str, Any], task_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"payload": dict(payload)}
        if task_id is not None:
            body["task_id"] = task_id
        return self.request("/work/enqueue", body)

    def complete(self, task_id: str, lease_token: str, result: Dict[str, Any]) -> Dict[str, Any]:
        response = self.request("/work/complete", {"worker_id": self.worker_id, "task_id": task_id, "lease_token": lease_token, "result": result})
        if response.get("completed") is not True:
            raise ComputeWorkerError(f"coordinator rejected completion for task {task_id}")
        return response

    def release(self, task_id: str, lease_token: str, error: str) -> Dict[str, Any]:
        response = self.request("/work/release", {"worker_id": self.worker_id, "task_id": task_id, "lease_token": lease_token, "error": error})
        if response.get("released") is not True:
            raise ComputeWorkerError(f"coordinator rejected release for task {task_id}")
        return response


def execute_compute_task(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ComputeWorkerError("task payload must be an object")
    kind = str(payload.get("kind") or "").strip()
    if kind == "lead_prepare":
        leads = payload.get("leads")
        if not isinstance(leads, list):
            raise ComputeWorkerError("lead_prepare requires a leads list")
        minimum_score = payload.get("minimum_score", 0)
        result = process_leads(leads, minimum_score=minimum_score)
        return {"kind": kind, "leads": result, "count": len(result)}
    if kind == "agent_task":
        agent = str(payload.get("agent") or "").strip()
        if not agent:
            raise ComputeWorkerError("agent_task requires agent")
        handler = advanced_handler_registry().get(agent)
        if handler is None:
            raise ComputeWorkerError(f"agent_task is not supported for stateless distributed agent: {agent}")
        task_payload = payload.get("payload", {})
        if not isinstance(task_payload, Mapping):
            raise ComputeWorkerError("agent_task payload must be an object")
        result = handler(agent, task_payload, None)
        return {"kind": kind, "agent": agent, "result": result}
    raise ComputeWorkerError(f"unsupported compute task kind: {kind or '<missing>'}")


def run_worker(client: ComputeWorkerClient, *, idle_seconds: float = 2.0, heartbeat_seconds: float = 15.0, stop_event=None) -> None:
    if idle_seconds <= 0 or heartbeat_seconds <= 0:
        raise ValueError("worker intervals must be positive")
    stop_event = stop_event or _NeverStop()
    backoff = 1.0
    last_heartbeat = 0.0
    while not stop_event.is_set():
        try:
            if not client._registered:
                client.register()
                client._registered = True
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                client.heartbeat(0)
                last_heartbeat = now
            task = client.claim()
            backoff = 1.0
        except ComputeWorkerError:
            client._registered = False
            if stop_event.wait(backoff):
                break
            backoff = min(30.0, backoff * 2.0)
            continue
        if task is None:
            stop_event.wait(idle_seconds)
            continue
        try:
            result = execute_compute_task(task["payload"])
            client.complete(task["task_id"], task["lease_token"], result)
        except Exception as error:
            try:
                client.release(task["task_id"], task["lease_token"], str(error))
            except ComputeWorkerError:
                client._registered = False


class _NeverStop:
    def is_set(self) -> bool:
        return False

    def wait(self, seconds: float) -> bool:
        time.sleep(seconds)
        return False


def client_from_environment() -> ComputeWorkerClient:
    url = os.environ.get("THORIO_COMPUTE_COORDINATOR_URL", "")
    token = os.environ.get("THORIO_COMPUTE_AUTH_TOKEN", "")
    worker_id = os.environ.get("THORIO_WORKER_ID", "") or local_worker_identity().worker_id
    if not url:
        raise RuntimeError("THORIO_COMPUTE_COORDINATOR_URL is required")
    if not token:
        raise RuntimeError("THORIO_COMPUTE_AUTH_TOKEN is required")
    return ComputeWorkerClient(url, token, worker_id, int(os.environ.get("THORIO_COMPUTE_HTTP_TIMEOUT", "20")))


ComputeWorkerClient._registered = False


if __name__ == "__main__":
    run_worker(client_from_environment())
