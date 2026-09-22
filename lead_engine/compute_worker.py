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
from .nvidia_provider import CommandResult, NvidiaProvider
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
    """Execute one real NCCL process for every allocated GPU and verify every rank."""
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
    gpu_bindings = participant.get("gpu_bindings")
    if not isinstance(gpu_bindings, list) or not gpu_bindings:
        raise ComputeWorkerError("launch plan is missing exact GPU bindings")

    world_size = int(plan["world_size"])
    process_count = int(participant["process_count"])
    if world_size < 2 or process_count != len(gpu_bindings):
        raise ComputeWorkerError("launch plan has an invalid distributed process contract")

    normalized_bindings = []
    seen_ranks: set[int] = set()
    seen_devices: set[str] = set()
    seen_uuids: set[str] = set()
    for binding in gpu_bindings:
        if not isinstance(binding, dict):
            raise ComputeWorkerError("launch plan contains a non-object GPU binding")
        gpu_id = str(binding.get("gpu_id") or "").strip()
        gpu_uuid = str(binding.get("gpu_uuid") or "").strip()
        device_id = gpu_id if gpu_id.isdigit() else gpu_id.removeprefix("gpu-")
        rank = int(binding.get("rank", -1))
        local_rank = int(binding.get("local_rank", -1))
        if (
            not device_id.isdigit()
            or not gpu_uuid
            or rank < 0
            or rank >= world_size
            or local_rank < 0
            or local_rank >= process_count
            or rank in seen_ranks
            or device_id in seen_devices
            or gpu_uuid in seen_uuids
        ):
            raise ComputeWorkerError("launch plan contains invalid or ambiguous per-GPU process bindings")
        seen_ranks.add(rank)
        seen_devices.add(device_id)
        seen_uuids.add(gpu_uuid)
        normalized_bindings.append({
            **binding,
            "gpu_id": gpu_id,
            "gpu_uuid": gpu_uuid,
            "device_id": device_id,
            "rank": rank,
            "local_rank": local_rank,
        })

    # This worker owns only its participant-local subset of the global ranks.
    # The coordinator's durable launch plan is responsible for proving complete
    # world coverage; this worker must only validate that its own bindings are
    # unique, in-range, and internally unambiguous.

    if isinstance(runtime, NvidiaRuntime):
        gpu_identity = runtime.verify_gpu_bindings(normalized_bindings)
    else:
        gpu_identity = {"verified": False, "verification_source": "injected_runtime"}

    client.fabric_state(attempt_id, generation, lease_token, "launching")
    stop_heartbeat = threading.Event()
    heartbeat_failed = threading.Event()
    heartbeat_error: list[str] = []
    process_lock = threading.Lock()
    process_holder: list[Any] = []

    def stop_processes() -> None:
        with process_lock:
            processes = list(process_holder)
        for process in processes:
            try:
                if process.poll() is not None:
                    continue
            except Exception:
                pass
            try:
                if os.name == "posix" and getattr(process, "pid", None) is not None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        for process in processes:
            try:
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
                    stop_processes()
                    return
            except Exception as error:
                heartbeat_error.append(str(error))
                heartbeat_failed.set()
                stop_processes()
                return

    thread = threading.Thread(target=beat, daemon=True)
    try:
        local = runtime.verify_local()
        provider_runner = (
            None
            if getattr(runtime, "runner", None) is None
            else lambda args, timeout: CommandResult(*runtime.runner(args, timeout))
        )
        rdma_evidence: Mapping[str, Any] | None = None
        gpu_nic_locality: Sequence[Mapping[str, object]] = ()
        host, port_text = str(plan["rendezvous_endpoint"]).rsplit(":", 1)
        port = int(port_text)
        command = runtime.distributed_process_command()
        client.fabric_state(attempt_id, generation, lease_token, "active")

        process_specs = []
        for binding in sorted(normalized_bindings, key=lambda item: item["rank"]):
            execution_env = os.environ.copy()
            execution_env.update({
                "CUDA_VISIBLE_DEVICES": binding["device_id"],
                "MASTER_ADDR": host,
                "MASTER_PORT": str(port),
                "RANK": str(binding["rank"]),
                "WORLD_SIZE": str(world_size),
                "LOCAL_RANK": "0",
                "LOCAL_WORLD_SIZE": "1",
                "THORIO_EXPECTED_WORLD_SIZE": str(world_size),
                "THORIO_EXPECTED_NNODES": str(int(plan["nnodes"])),
                "THORIO_EXPECTED_RANK": str(binding["rank"]),
                "THORIO_EXPECTED_GPU_UUID": binding["gpu_uuid"],
                "NCCL_DEBUG": "INFO",
                "NCCL_DEBUG_SUBSYS": "NET",
                "THORIO_FABRIC_ATTEMPT_ID": attempt_id,
                "THORIO_FABRIC_GENERATION": str(generation),
            })
            process_specs.append((binding, execution_env))

        results = []
        if runner is not None:
            thread.start()
            for binding, execution_env in process_specs:
                if heartbeat_failed.is_set():
                    raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
                rc, stdout, stderr = runner(command, runtime.timeout_seconds, execution_env)
                results.append((binding, int(rc), str(stdout), str(stderr)))
        else:
            for binding, execution_env in process_specs:
                if heartbeat_failed.is_set():
                    raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
                popen_kwargs = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "env": execution_env,
                }
                if os.name == "posix":
                    popen_kwargs["start_new_session"] = True
                elif os.name == "nt":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                process = subprocess.Popen(command, **popen_kwargs)
                with process_lock:
                    process_holder.append(process)
            thread.start()
            # process_holder is ordered exactly like process_specs.
            for binding, process in zip(
                [item[0] for item in process_specs],
                list(process_holder),
            ):
                try:
                    stdout, stderr = process.communicate(timeout=runtime.timeout_seconds)
                    rc = process.returncode
                except subprocess.TimeoutExpired:
                    stop_processes()
                    raise ComputeWorkerError(
                        f"distributed NVIDIA rank {binding['rank']} timed out"
                    )
                results.append((binding, int(rc), str(stdout), str(stderr)))

        if heartbeat_failed.is_set():
            stop_processes()
            raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")

        process_evidence = []
        failures = []
        for binding, rc, stdout, stderr in results:
            if rc != 0:
                failures.append(
                    f"rank {binding['rank']} ({binding['gpu_uuid']}): {(stderr or stdout).strip()[:2000]}"
                )
                continue
            probe = runtime.validate_distributed_probe_output(
                stdout,
                world_size,
                expected_rank=int(binding["rank"]),
                expected_gpu_uuid=str(binding["gpu_uuid"]),
                log_output=stdout + "\n" + stderr,
            )
            if int(plan["nnodes"]) > 1 and str(probe.get("network_transport") or "").strip().upper() == "IB" and rdma_evidence is None:
                network_snapshot = NvidiaProvider(
                    node_id=client.worker_id,
                    runner=provider_runner,
                ).discover()
                network_evidence = network_snapshot.evidence if isinstance(network_snapshot.evidence, Mapping) else {}
                rdma_candidate = network_evidence.get("network", {}).get("rdma", {}) if isinstance(network_evidence.get("network"), Mapping) else {}
                if not isinstance(rdma_candidate, Mapping):
                    raise NvidiaRuntimeError("IB execution requires verified local RDMA discovery evidence")
                rdma_evidence = rdma_candidate
                network_payload = network_evidence.get("network")
                locality_candidate = network_payload.get("gpu_nic_locality") if isinstance(network_payload, Mapping) else None
                if isinstance(locality_candidate, list):
                    gpu_nic_locality = tuple(
                        row for row in locality_candidate if isinstance(row, Mapping)
                    )
            path_evidence = runtime.validate_nccl_transport_against_rdma(
                stdout + "\n" + stderr,
                rdma_evidence or {},
                gpu_uuid=str(binding["gpu_uuid"]),
                gpu_nic_locality=gpu_nic_locality,
            ) if int(plan["nnodes"]) > 1 else {
                "rdma_devices": (),
                "verified_rdma_devices": (),
            }
            process_evidence.append({
                "rank": int(binding["rank"]),
                "local_rank": int(binding["local_rank"]),
                "gpu_binding": dict(binding),
                "probe": probe,
                "network_transport": probe.get("network_transport"),
                "gpu_direct_rdma": probe.get("gpu_direct_rdma"),
                "network_evidence_lines": list(probe.get("network_evidence_lines") or ()),
                "rdma_devices": list(path_evidence.get("rdma_devices") or ()),
                "verified_rdma_devices": list(path_evidence.get("verified_rdma_devices") or ()),
                "hca_selections": list(path_evidence.get("hca_selections") or ()),
                "verified_hca_selections": list(path_evidence.get("verified_hca_selections") or ()),
                "verified_rdma_links": list(path_evidence.get("verified_rdma_links") or ()),
                "gpu_nic_locality": path_evidence.get("gpu_nic_locality"),
                "stdout": stdout[-4000:],
            })

        if failures:
            raise NvidiaRuntimeError("distributed NCCL launch failed: " + "; ".join(failures))

        if len(process_evidence) != len(normalized_bindings):
            raise NvidiaRuntimeError(
                f"distributed NCCL execution produced {len(process_evidence)} verified local ranks; expected {len(normalized_bindings)}"
            )

        evidence = {
            "verified": True,
            "backend": "nccl",
            "collective": "all_reduce",
            "local_runtime": local,
            "gpu_identity": gpu_identity,
            "gpu_bindings": normalized_bindings,
            "process_evidence": process_evidence,
            "attempt_id": attempt_id,
            "generation": generation,
            "worker_id": client.worker_id,
            "node_rank": int(participant["node_rank"]),
            "world_size": world_size,
            "nnodes": int(plan["nnodes"]),
            "command": list(command),
            "rendezvous_endpoint": plan["rendezvous_endpoint"],
        }
        if not client.fabric_record_verification(
            attempt_id, generation, lease_token, evidence
        ).get("ok", True):
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
        stop_processes()
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