"""Free remote worker client for the shared compute coordinator."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Mapping, Optional

from .advanced_agent_logic import DISCOVERY_TARGETS, SOCIAL_TARGETS, discovery_finding, social_research
from .compute_pool import local_worker_identity
from .nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError
from .lead_pipeline import process_leads
from .lead_sort import sort_by_score


class ComputeWorkerError(RuntimeError):
    pass


@dataclass
class ComputeWorkerClient:
    coordinator_url: str
    auth_token: str
    worker_id: str
    timeout_seconds: int = 20
    _registered: bool = field(default=False, init=False, repr=False)

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
        executable_agents = sorted(set(DISCOVERY_TARGETS) | set(SOCIAL_TARGETS))
        gpu_resources = []
        for gpu in identity.gpu_resources:
            item = asdict(gpu)
            item["health_state"] = gpu.health_state.value
            item["availability_state"] = gpu.availability_state.value
            gpu_resources.append(item)
        result = self.request("/workers/register", {
            "worker_id": identity.worker_id,
            "hostname": identity.hostname,
            "architecture": identity.architecture,
            "cpu_count": identity.cpu_count,
            "memory_mb": identity.memory_mb,
            "capabilities": list(identity.capabilities) + ["lead_prepare"] + executable_agents,
            "gpu_resources": gpu_resources,
            "driver_version": identity.driver_version,
            "cuda_version": identity.cuda_version,
            "nccl_version": identity.nccl_version,
            "nic_names": list(identity.nic_names),
            "gpu_discovery_state": identity.gpu_discovery_state,
            "gpu_discovery_error": identity.gpu_discovery_error,
        })
        self._registered = True
        return result

    def heartbeat(self, current_load: int = 0) -> Dict[str, Any]:
        return self.request("/workers/heartbeat", {"worker_id": self.worker_id, "current_load": current_load})

    def fabric_assignments(self) -> list[Dict[str, Any]]:
        response = self.request("/fabric/assignments", {"worker_id": self.worker_id})
        return list(response.get("assignments", []))

    def fabric_heartbeat(self, attempt_id: str, generation: int, lease_token: str) -> Dict[str, Any]:
        return self.request("/fabric/heartbeat", {
            "attempt_id": attempt_id, "generation": generation,
            "worker_id": self.worker_id, "lease_token": lease_token,
        })

    def fabric_state(self, attempt_id: str, generation: int, lease_token: str, status: str, error: str = "") -> Dict[str, Any]:
        return self.request("/fabric/state", {
            "attempt_id": attempt_id, "generation": generation,
            "worker_id": self.worker_id, "lease_token": lease_token,
            "status": status, "error": error,
        })

    def fabric_launch_plan(self, attempt_id: str, generation: int, lease_token: str, rendezvous_endpoint: str) -> Dict[str, Any]:
        return self.request("/fabric/launch-plan", {
            "attempt_id": attempt_id, "generation": generation,
            "worker_id": self.worker_id, "lease_token": lease_token,
            "rendezvous_endpoint": rendezvous_endpoint,
        })

    def fabric_record_verification(self, attempt_id: str, generation: int, lease_token: str, verification: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("/fabric/verification", {
            "attempt_id": attempt_id, "generation": generation,
            "worker_id": self.worker_id, "lease_token": lease_token,
            "verification": verification,
        })

    def fabric_converge(self, attempt_id: str, generation: int, lease_token: str) -> Dict[str, Any]:
        return self.request("/fabric/converge", {
            "attempt_id": attempt_id, "generation": generation,
            "worker_id": self.worker_id, "lease_token": lease_token,
        })

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

    def checkpoint_lead_prepare(self, task_id: str, lease_token: str, items: list[Dict[str, Any]]) -> Dict[str, Any]:
        return self.request("/work/checkpoint", {
            "worker_id": self.worker_id,
            "task_id": task_id,
            "lease_token": lease_token,
            "items": items,
        })

    def checkpoint_results(self, task_id: str) -> Dict[str, Any]:
        return self.request(f"/work/checkpoints/{task_id}")

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


def execute_checkpointed_lead_prepare(
    client: ComputeWorkerClient,
    task_id: str,
    lease_token: str,
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    leads = payload.get("leads")
    if not isinstance(leads, list):
        raise ComputeWorkerError("lead_prepare requires a leads list")
    minimum_score = payload.get("minimum_score", 0)
    batch_size = int(payload.get("checkpoint_batch_size", 25))
    if batch_size <= 0:
        raise ComputeWorkerError("checkpoint_batch_size must be positive")

    for start in range(0, len(leads), batch_size):
        batch = leads[start:start + batch_size]
        prepared_input = []
        item_keys = []
        for lead in batch:
            if not isinstance(lead, dict):
                raise ComputeWorkerError("lead_prepare leads must contain objects")
            item_key = str(lead.get("__checkpoint_item_key") or "").strip()
            if not item_key:
                raise ComputeWorkerError("coordinator did not attach a checkpoint item key")
            item_keys.append(item_key)
            prepared_item = {key: value for key, value in lead.items() if key != "__checkpoint_item_key"}
            prepared_item["__checkpoint_item_key"] = item_key
            prepared_input.append(prepared_item)
        result = process_leads(prepared_input, minimum_score=minimum_score)
        result_by_key = {}
        for item in result:
            if not isinstance(item, dict):
                raise ComputeWorkerError("lead preparation returned a non-object")
            item_key = str(item.get("__checkpoint_item_key") or "").strip()
            if item_key not in item_keys:
                raise ComputeWorkerError("lead preparation lost checkpoint item identity")
            stored_item = {key: value for key, value in item.items() if key != "__checkpoint_item_key"}
            result_by_key[item_key] = stored_item
        checkpoint_items = [{"item_key": key, "result": result_by_key.get(key)} for key in item_keys]
        client.checkpoint_lead_prepare(task_id, lease_token, checkpoint_items)

    stored = client.checkpoint_results(task_id)
    stored_results = [item for item in stored.get("results", []) if isinstance(item, dict)]
    ordered = sort_by_score(stored_results)
    return {"kind": "lead_prepare", "leads": ordered, "count": len(ordered)}

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
        task_payload = payload.get("payload", {})
        if not isinstance(task_payload, Mapping):
            raise ComputeWorkerError("agent_task payload must be an object")
        if agent in DISCOVERY_TARGETS:
            result = discovery_finding(agent, task_payload, None)
            return {"kind": kind, "agent": agent, "result": result}
        if agent in SOCIAL_TARGETS:
            result = social_research(agent, task_payload, None)
            return {"kind": kind, "agent": agent, "result": result}
        raise ComputeWorkerError(f"agent_task is not supported for stateless distributed agent: {agent}")
    raise ComputeWorkerError(f"unsupported compute task kind: {kind or '<missing>'}")


def run_fabric_verification(
    client: ComputeWorkerClient,
    assignment: Mapping[str, Any],
    *,
    rendezvous_endpoint: str,
    heartbeat_seconds: float = 10.0,
    convergence_timeout_seconds: float = 60.0,
    runtime: NvidiaRuntime | None = None,
    runner=None,
) -> Dict[str, Any]:
    """Run the real NVIDIA distributed probe without completing business work."""
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    if convergence_timeout_seconds <= 0:
        raise ValueError("convergence_timeout_seconds must be positive")
    attempt_id = str(assignment["attempt_id"])
    generation = int(assignment["generation"])
    lease_token = str(assignment["lease_token"])
    plan = client.fabric_launch_plan(attempt_id, generation, lease_token, rendezvous_endpoint)
    participant = next((item for item in plan["workers"] if item["worker_id"] == client.worker_id), None)
    if participant is None:
        raise ComputeWorkerError("worker is not present in the durable launch plan")
    runtime = runtime or NvidiaRuntime()
    client.fabric_state(attempt_id, generation, lease_token, "launching")
    stop_heartbeat = threading.Event()
    heartbeat_failed = threading.Event()
    heartbeat_error: list[str] = []
    process_lock = threading.Lock()
    process_holder = {"process": None}

    def stop_process() -> None:
        with process_lock:
            process = process_holder["process"]
        if process is None:
            return

        if os.name == "posix":
            process_group_id = getattr(process, "pid", None)
            if process_group_id is not None:
                group_exists = False
                try:
                    os.killpg(process_group_id, 0)
                    group_exists = True
                except ProcessLookupError:
                    group_exists = False
                except PermissionError:
                    group_exists = True
                if group_exists:
                    try:
                        os.killpg(process_group_id, signal.SIGTERM)
                    except ProcessLookupError:
                        group_exists = False
                    if group_exists:
                        try:
                            process.wait(timeout=2)
                        except Exception:
                            try:
                                os.killpg(process_group_id, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            try:
                                process.wait(timeout=2)
                            except Exception:
                                pass
                return

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

    def beat() -> None:
        while not stop_heartbeat.wait(heartbeat_seconds):
            try:
                response = client.fabric_heartbeat(attempt_id, generation, lease_token)
                if response.get("ok") is not True:
                    heartbeat_error.append("coordinator rejected fabric heartbeat")
                    heartbeat_failed.set()
                    stop_process()
                    return
            except Exception as error:
                heartbeat_error.append(str(error))
                heartbeat_failed.set()
                stop_process()
                return

    thread = threading.Thread(target=beat, daemon=True)
    try:
        local = runtime.verify_local()
        host, port_text = str(plan["rendezvous_endpoint"]).rsplit(":", 1)
        command = runtime.distributed_command(
            world_size=int(plan["world_size"]), node_rank=int(participant["node_rank"]),
            nnodes=int(plan["nnodes"]), master_addr=host, master_port=int(port_text),
            rendezvous_id=str(plan["rendezvous_id"]), process_count=int(participant["process_count"]),
        )
        client.fabric_state(attempt_id, generation, lease_token, "active")

        if runner is None:
            popen_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            elif os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(command, **popen_kwargs)
            with process_lock:
                process_holder["process"] = process
            thread.start()
            if heartbeat_failed.is_set():
                stop_process()
                raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
            try:
                stdout, stderr = process.communicate(timeout=runtime.timeout_seconds)
                rc = process.returncode
            except subprocess.TimeoutExpired:
                stop_process()
                stdout, stderr = process.communicate()
                raise ComputeWorkerError("distributed NVIDIA launch timed out")
        else:
            thread.start()
            if heartbeat_failed.is_set():
                raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
            rc, stdout, stderr = runner(command, runtime.timeout_seconds)

        if heartbeat_failed.is_set():
            stop_process()
            raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
        if rc != 0:
            raise NvidiaRuntimeError(f"distributed NCCL launch failed: {(stderr or stdout).strip()[:4000]}")
        probe = runtime.validate_distributed_probe_output(str(stdout), int(plan["world_size"]))
        if heartbeat_failed.is_set():
            raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
        evidence = {
            "verified": True, "local_runtime": local, "probe": probe, "attempt_id": attempt_id,
            "generation": generation, "worker_id": client.worker_id,
            "node_rank": int(participant["node_rank"]), "world_size": int(plan["world_size"]),
            "nnodes": int(plan["nnodes"]), "command": command, "stdout": str(stdout)[-4000:],
        }
        if not client.fabric_record_verification(attempt_id, generation, lease_token, evidence).get("ok", True):
            raise ComputeWorkerError("coordinator rejected execution verification")
        deadline = time.monotonic() + convergence_timeout_seconds
        convergence = client.fabric_converge(attempt_id, generation, lease_token)
        while convergence.get("converged") is not True and time.monotonic() < deadline:
            if heartbeat_failed.is_set():
                raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
            if stop_heartbeat.wait(min(heartbeat_seconds, 1.0)):
                break
            convergence = client.fabric_converge(attempt_id, generation, lease_token)
        if convergence.get("converged") is not True:
            raise ComputeWorkerError(
                f"distributed execution did not converge: {convergence.get('reason', 'unknown')}"
            )
        evidence["convergence"] = convergence
        return evidence
    except Exception as error:
        try:
            client.fabric_state(attempt_id, generation, lease_token, "failed", str(error))
        except Exception:
            pass
        raise
    finally:
        stop_process()
        stop_heartbeat.set()
        if thread.is_alive():
            thread.join(timeout=2)


def run_worker(
    client: ComputeWorkerClient,
    *,
    idle_seconds: float = 2.0,
    heartbeat_seconds: float = 15.0,
    fabric_rendezvous_endpoint: str | None = None,
    stop_event=None,
) -> None:
    if idle_seconds <= 0 or heartbeat_seconds <= 0:
        raise ValueError("worker intervals must be positive")
    stop_event = stop_event or _NeverStop()
    fabric_rendezvous_endpoint = (
        fabric_rendezvous_endpoint
        or os.environ.get("THORIO_FABRIC_RENDEZVOUS_ENDPOINT", "")
    ).strip()
    backoff = 1.0
    last_heartbeat = 0.0
    while not stop_event.is_set():
        try:
            if not client._registered:
                client.register()
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                client.heartbeat(1 if getattr(client, "_active_task", None) else 0)
                last_heartbeat = now
            assignments = client.fabric_assignments()
            if assignments:
                if not fabric_rendezvous_endpoint:
                    for assignment in assignments:
                        response = client.fabric_state(
                            str(assignment["attempt_id"]),
                            int(assignment["generation"]),
                            str(assignment["lease_token"]),
                            "failed",
                            "THORIO_FABRIC_RENDEZVOUS_ENDPOINT is required for fabric execution",
                        )
                        if response.get("ok") is not True:
                            raise ComputeWorkerError("coordinator rejected fabric failure state")
                else:
                    for assignment in assignments:
                        try:
                            run_fabric_verification(
                                client,
                                assignment,
                                rendezvous_endpoint=fabric_rendezvous_endpoint,
                            )
                        except NvidiaRuntimeError:
                            if stop_event.wait(idle_seconds):
                                break
                backoff = 1.0
                continue
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
        client._active_task = task["task_id"]
        try:
            payload = task["payload"]
            if "compute_requirements" in payload and not isinstance(task.get("physical_allocation"), Mapping):
                raise ComputeWorkerError("coordinator did not assign a physical execution allocation")
            if str(payload.get("kind") or "").strip() == "lead_prepare":
                result = execute_checkpointed_lead_prepare(
                    client, task["task_id"], task["lease_token"], payload
                )
            else:
                result = execute_compute_task(payload)
            client.complete(task["task_id"], task["lease_token"], result)
        except Exception as error:
            try:
                client.release(task["task_id"], task["lease_token"], str(error))
            except ComputeWorkerError:
                client._registered = False
        finally:
            client._active_task = None


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


if __name__ == "__main__":
    run_worker(client_from_environment())
