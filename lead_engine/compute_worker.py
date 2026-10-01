"""Free remote worker client for the shared compute coordinator."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .advanced_agent_logic import DISCOVERY_TARGETS, SOCIAL_TARGETS, discovery_finding, social_research
from .compute_pool import local_worker_identity
from .fabric_topology_runtime import FabricTopologyRuntimeError, verify_provider_snapshot
from .nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError
from .nvidia_provider import CommandResult, NvidiaProvider
from .lead_pipeline import process_leads
from .gpu_execution_runtime import execute_gpu_workload
from .fabric_verification import FabricVerificationMatrix
from .execution_fabric_contract import ExecutionMode
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
        request = urllib.request.Request(self.coordinator_url + path, data=body, method="GET" if body is None else "POST", headers={"Authorization": f"Bearer {self.auth_token}", "Content-Type": "application/json"})
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
            item = asdict(gpu); item["health_state"] = gpu.health_state.value; item["availability_state"] = gpu.availability_state.value; gpu_resources.append(item)
        result = self.request("/workers/register", {"worker_id": identity.worker_id, "hostname": identity.hostname, "architecture": identity.architecture, "cpu_count": identity.cpu_count, "memory_mb": identity.memory_mb, "capabilities": list(identity.capabilities) + ["lead_prepare"] + executable_agents, "gpu_resources": gpu_resources, "driver_version": identity.driver_version, "cuda_version": identity.cuda_version, "nccl_version": identity.nccl_version, "nic_names": list(identity.nic_names), "gpu_discovery_state": identity.gpu_discovery_state, "gpu_discovery_error": identity.gpu_discovery_error,
            "domain_id": identity.domain_id, "physical_fabric_evidence": dict(identity.physical_fabric_evidence)})
        self._registered = True
        return result

    def heartbeat(self, current_load: int = 0) -> Dict[str, Any]: return self.request("/workers/heartbeat", {"worker_id": self.worker_id, "current_load": current_load})
    def fabric_assignments(self) -> list[Dict[str, Any]]: return list(self.request("/fabric/assignments", {"worker_id": self.worker_id}).get("assignments", []))
    def fleet_observability(self) -> Dict[str, Any]: return self.request("/fabric/fleet")
    def free_compute_status(self) -> Dict[str, Any]: return self.request("/fabric/acquisition/status")
    def fabric_heartbeat(self, attempt_id: str, generation: int, lease_token: str) -> Dict[str, Any]: return self.request("/fabric/heartbeat", {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token})
    def fabric_state(self, attempt_id: str, generation: int, lease_token: str, status: str, error: str = "") -> Dict[str, Any]: return self.request("/fabric/state", {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token, "status": status, "error": error})
    def fabric_launch_plan(self, attempt_id: str, generation: int, lease_token: str, rendezvous_endpoint: str) -> Dict[str, Any]: return self.request("/fabric/launch-plan", {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token, "rendezvous_endpoint": rendezvous_endpoint})
    def fabric_record_verification(self, attempt_id: str, generation: int, lease_token: str, verification: Dict[str, Any]) -> Dict[str, Any]: return self.request("/fabric/verification", {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token, "verification": verification})
    def fabric_record_active_gdrdma_measurement(self, attempt_id: str, generation: int, lease_token: str, path_id: str, measurement: Dict[str, Any], evidence: Dict[str, Any] | None = None, observed_at: float | None = None) -> Dict[str, Any]:
        body = {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token, "path_id": path_id, "measurement": dict(measurement), "evidence": dict(evidence or {})}
        if observed_at is not None:
            body["observed_at"] = float(observed_at)
        return self.request("/fabric/active-gdrdma-measurement", body)
    def gpu_record_verification(self, attempt_id: str, generation: int, lease_token: str, verification: Dict[str, Any]) -> Dict[str, Any]: return self.request("/fabric/gpu-verification", {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token, "verification": verification})
    def fabric_converge(self, attempt_id: str, generation: int, lease_token: str) -> Dict[str, Any]: return self.request("/fabric/converge", {"attempt_id": attempt_id, "generation": generation, "worker_id": self.worker_id, "lease_token": lease_token})
    def claim(self) -> Optional[Dict[str, Any]]:
        result = self.request("/work/claim", {"worker_id": self.worker_id}); return result if result.get("task_id") else None
    def status(self, task_id: str) -> Dict[str, Any]: return self.request(f"/work/status/{task_id}")
    def enqueue(self, payload: Mapping[str, Any], task_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"payload": dict(payload)}
        if task_id is not None: body["task_id"] = task_id
        return self.request("/work/enqueue", body)
    def checkpoint_lead_prepare(self, task_id: str, lease_token: str, items: list[Dict[str, Any]]) -> Dict[str, Any]: return self.request("/work/checkpoint", {"worker_id": self.worker_id, "task_id": task_id, "lease_token": lease_token, "items": items})
    def checkpoint_results(self, task_id: str) -> Dict[str, Any]: return self.request(f"/work/checkpoints/{task_id}")
    def complete(self, task_id: str, lease_token: str, result: Dict[str, Any]) -> Dict[str, Any]:
        response = self.request("/work/complete", {"worker_id": self.worker_id, "task_id": task_id, "lease_token": lease_token, "result": result})
        if response.get("completed") is not True: raise ComputeWorkerError(f"coordinator rejected completion for task {task_id}")
        return response
    def release(self, task_id: str, lease_token: str, error: str) -> Dict[str, Any]:
        response = self.request("/work/release", {"worker_id": self.worker_id, "task_id": task_id, "lease_token": lease_token, "error": error})
        if response.get("released") is not True: raise ComputeWorkerError(f"coordinator rejected release for task {task_id}")
        return response


def execute_checkpointed_lead_prepare(client: ComputeWorkerClient, task_id: str, lease_token: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    leads = payload.get("leads")
    if not isinstance(leads, list): raise ComputeWorkerError("lead_prepare requires a leads list")
    minimum_score = payload.get("minimum_score", 0); batch_size = int(payload.get("checkpoint_batch_size", 25))
    if batch_size <= 0: raise ComputeWorkerError("checkpoint_batch_size must be positive")
    for start in range(0, len(leads), batch_size):
        batch = leads[start:start + batch_size]; prepared_input=[]; item_keys=[]
        for lead in batch:
            if not isinstance(lead, dict): raise ComputeWorkerError("lead_prepare leads must contain objects")
            item_key = str(lead.get("__checkpoint_item_key") or "").strip()
            if not item_key: raise ComputeWorkerError("coordinator did not attach a checkpoint item key")
            item_keys.append(item_key); prepared_item={key:value for key,value in lead.items() if key != "__checkpoint_item_key"}; prepared_item["__checkpoint_item_key"]=item_key; prepared_input.append(prepared_item)
        result=process_leads(prepared_input, minimum_score=minimum_score); result_by_key={}
        for item in result:
            if not isinstance(item, dict): raise ComputeWorkerError("lead preparation returned a non-object")
            item_key=str(item.get("__checkpoint_item_key") or "").strip()
            if item_key not in item_keys: raise ComputeWorkerError("lead preparation lost checkpoint item identity")
            result_by_key[item_key]={key:value for key,value in item.items() if key != "__checkpoint_item_key"}
        client.checkpoint_lead_prepare(task_id, lease_token, [{"item_key":key,"result":result_by_key.get(key)} for key in item_keys])
    stored=client.checkpoint_results(task_id); stored_results=[item for item in stored.get("results",[]) if isinstance(item,dict)]; ordered=sort_by_score(stored_results)
    return {"kind":"lead_prepare","leads":ordered,"count":len(ordered)}


def execute_compute_task(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, Mapping): raise ComputeWorkerError("task payload must be an object")
    kind=str(payload.get("kind") or "").strip()
    if kind == "lead_prepare":
        leads=payload.get("leads")
        if not isinstance(leads,list): raise ComputeWorkerError("lead_prepare requires a leads list")
        result=process_leads(leads, minimum_score=payload.get("minimum_score",0)); return {"kind":kind,"leads":result,"count":len(result)}
    if kind == "agent_task":
        agent=str(payload.get("agent") or "").strip(); task_payload=payload.get("payload",{})
        if not agent: raise ComputeWorkerError("agent_task requires agent")
        if not isinstance(task_payload,Mapping): raise ComputeWorkerError("agent_task payload must be an object")
        if agent in DISCOVERY_TARGETS: return {"kind":kind,"agent":agent,"result":discovery_finding(agent,task_payload,None)}
        if agent in SOCIAL_TARGETS: return {"kind":kind,"agent":agent,"result":social_research(agent,task_payload,None)}
        raise ComputeWorkerError(f"agent_task is not supported for stateless distributed agent: {agent}")
    raise ComputeWorkerError(f"unsupported compute task kind: {kind or '<missing>'}")


def run_fabric_verification(client: ComputeWorkerClient, assignment: Mapping[str, Any], *, rendezvous_endpoint: str, heartbeat_seconds: float = 10.0, convergence_timeout_seconds: float = 60.0, runtime: NvidiaRuntime | None = None, runner=None) -> Dict[str, Any]:
    if heartbeat_seconds <= 0: raise ValueError("heartbeat_seconds must be positive")
    if convergence_timeout_seconds <= 0: raise ValueError("convergence_timeout_seconds must be positive")
    attempt_id=str(assignment["attempt_id"]); generation=int(assignment["generation"]); lease_token=str(assignment["lease_token"])
    plan=client.fabric_launch_plan(attempt_id,generation,lease_token,rendezvous_endpoint); participant=next((item for item in plan["workers"] if item["worker_id"]==client.worker_id),None)
    if participant is None: raise ComputeWorkerError("worker is not present in the durable launch plan")
    runtime=runtime or NvidiaRuntime(); gpu_bindings=participant.get("gpu_bindings")
    if not isinstance(gpu_bindings,list) or not gpu_bindings: raise ComputeWorkerError("launch plan is missing exact GPU bindings")
    world_size=int(plan["world_size"]); process_count=int(participant["process_count"])
    if world_size < 2 or process_count != len(gpu_bindings): raise ComputeWorkerError("launch plan has an invalid distributed process contract")
    normalized_bindings=[]; seen_ranks=set(); seen_devices=set(); seen_uuids=set()
    for binding in gpu_bindings:
        if not isinstance(binding,dict): raise ComputeWorkerError("launch plan contains a non-object GPU binding")
        gpu_id=str(binding.get("gpu_id") or "").strip(); gpu_uuid=str(binding.get("gpu_uuid") or "").strip(); device_id=gpu_id if gpu_id.isdigit() else gpu_id.removeprefix("gpu-"); rank=int(binding.get("rank",-1)); local_rank=int(binding.get("local_rank",-1))
        if not device_id.isdigit() or not gpu_uuid or rank<0 or rank>=world_size or local_rank<0 or local_rank>=process_count or rank in seen_ranks or device_id in seen_devices or gpu_uuid in seen_uuids: raise ComputeWorkerError("launch plan contains invalid or ambiguous per-GPU process bindings")
        seen_ranks.add(rank); seen_devices.add(device_id); seen_uuids.add(gpu_uuid); normalized_bindings.append({**binding,"gpu_id":gpu_id,"gpu_uuid":gpu_uuid,"device_id":device_id,"rank":rank,"local_rank":local_rank})
    gpu_identity=runtime.verify_gpu_bindings(normalized_bindings) if isinstance(runtime,NvidiaRuntime) else {"verified":False,"verification_source":"injected_runtime"}
    client.fabric_state(attempt_id,generation,lease_token,"launching"); stop_heartbeat=threading.Event(); heartbeat_failed=threading.Event(); heartbeat_error=[]; process_lock=threading.Lock(); process_holder=[]
    def stop_processes():
        with process_lock: processes=list(process_holder)
        for process in processes:
            try:
                if process.poll() is not None: continue
            except Exception: pass
            try:
                if os.name=="posix" and getattr(process,"pid",None) is not None:
                    try: os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError: pass
                else: process.terminate()
            except Exception:
                try: process.kill()
                except Exception: pass
        for process in processes:
            try: process.wait(timeout=2)
            except Exception:
                try:
                    if os.name == "posix" and getattr(process, "pid", None) is not None:
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    else:
                        process.kill()
                    process.wait(timeout=2)
                except Exception: pass
    def beat():
        while not stop_heartbeat.wait(heartbeat_seconds):
            try:
                response=client.fabric_heartbeat(attempt_id,generation,lease_token)
                if response.get("ok") is not True: heartbeat_error.append("coordinator rejected fabric heartbeat"); heartbeat_failed.set(); stop_processes(); return
            except Exception as error: heartbeat_error.append(str(error)); heartbeat_failed.set(); stop_processes(); return
    thread=threading.Thread(target=beat,daemon=True)
    try:
        local=runtime.verify_local(); provider_runner=None if getattr(runtime,"runner",None) is None else lambda args,timeout: CommandResult(*runtime.runner(args,timeout)); rdma_evidence=None; gpu_nic_locality=(); physical_topology=None
        host,port_text=str(plan["rendezvous_endpoint"]).rsplit(":",1); port=int(port_text); command=runtime.distributed_process_command(); client.fabric_state(attempt_id,generation,lease_token,"active")
        process_specs=[]
        for binding in sorted(normalized_bindings,key=lambda item:item["rank"]):
            execution_env=os.environ.copy(); execution_env.update({"CUDA_VISIBLE_DEVICES":binding["device_id"],"MASTER_ADDR":host,"MASTER_PORT":str(port),"RANK":str(binding["rank"]),"WORLD_SIZE":str(world_size),"LOCAL_RANK":"0","LOCAL_WORLD_SIZE":"1","THORIO_EXPECTED_WORLD_SIZE":str(world_size),"THORIO_EXPECTED_NNODES":str(int(plan["nnodes"])),"THORIO_EXPECTED_RANK":str(binding["rank"]),"THORIO_EXPECTED_GPU_UUID":binding["gpu_uuid"],"NCCL_DEBUG":"INFO","NCCL_DEBUG_SUBSYS":"NET","THORIO_FABRIC_ATTEMPT_ID":attempt_id,"THORIO_FABRIC_GENERATION":str(generation)}); process_specs.append((binding,execution_env))
        results=[]
        if runner is not None:
            thread.start()
            for binding,execution_env in process_specs:
                if heartbeat_failed.is_set(): raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
                rc,stdout,stderr=runner(command,runtime.timeout_seconds,execution_env); results.append((binding,int(rc),str(stdout),str(stderr)))
        else:
            for binding,execution_env in process_specs:
                if heartbeat_failed.is_set(): raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
                popen_kwargs={"stdout":subprocess.PIPE,"stderr":subprocess.PIPE,"text":True,"env":execution_env}
                if os.name=="posix": popen_kwargs["start_new_session"]=True
                elif os.name=="nt": popen_kwargs["creationflags"]=subprocess.CREATE_NEW_PROCESS_GROUP
                process=subprocess.Popen(command,**popen_kwargs)
                with process_lock: process_holder.append(process)
            thread.start()
            process_items=list(zip([item[0] for item in process_specs], list(process_holder)))
            result_queue=__import__("queue").Queue()
            def collect_process(binding, process):
                try:
                    stdout, stderr = process.communicate(timeout=runtime.timeout_seconds)
                    result_queue.put((binding, process, int(process.returncode), str(stdout), str(stderr), None))
                except Exception as error:
                    result_queue.put((binding, process, None, "", "", error))
            collectors=[]
            for binding, process in process_items:
                collector=threading.Thread(target=collect_process,args=(binding,process),daemon=True)
                collector.start()
                collectors.append(collector)
            remaining=len(process_items)
            while remaining:
                binding, process, rc, stdout, stderr, error = result_queue.get()
                remaining -= 1
                if error is not None:
                    stop_processes()
                    if isinstance(error, subprocess.TimeoutExpired):
                        raise ComputeWorkerError(f"distributed NVIDIA rank {binding['rank']} timed out")
                    raise error
                results.append((binding,rc,stdout,stderr))
                if rc != 0:
                    stop_processes()
                    while remaining:
                        binding2, process2, rc2, stdout2, stderr2, error2 = result_queue.get()
                        remaining -= 1
                        if error2 is None:
                            results.append((binding2,rc2,stdout2,stderr2))
                        elif isinstance(error2, subprocess.TimeoutExpired):
                            results.append((binding2,143,"",f"terminated after rank {binding['rank']} failed"))
                        else:
                            results.append((binding2,143,"",str(error2)))
                    break
        if heartbeat_failed.is_set(): stop_processes(); raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
        process_evidence=[]; failures=[]
        for binding,rc,stdout,stderr in results:
            if rc != 0: failures.append(f"rank {binding['rank']} ({binding['gpu_uuid']}): {(stderr or stdout).strip()[:2000]}"); continue
            probe=runtime.validate_distributed_probe_output(stdout,world_size,expected_rank=int(binding["rank"]),expected_gpu_uuid=str(binding["gpu_uuid"]),log_output=stdout+"\n"+stderr)
            if int(plan["nnodes"])>1 and str(probe.get("network_transport") or "").strip().upper()=="IB" and rdma_evidence is None:
                network_snapshot=NvidiaProvider(node_id=client.worker_id,runner=provider_runner).discover(); network_evidence=network_snapshot.evidence if isinstance(network_snapshot.evidence,Mapping) else {}; rdma_candidate=network_evidence.get("network",{}).get("rdma",{}) if isinstance(network_evidence.get("network"),Mapping) else {}
                if not isinstance(rdma_candidate,Mapping): raise NvidiaRuntimeError("IB execution requires verified local RDMA discovery evidence")
                rdma_evidence=rdma_candidate; network_payload=network_evidence.get("network"); locality_candidate=network_payload.get("gpu_nic_locality") if isinstance(network_payload,Mapping) else None
                if isinstance(locality_candidate,list): gpu_nic_locality=tuple(row for row in locality_candidate if isinstance(row,Mapping))
                try:
                    physical_topology=verify_provider_snapshot(network_snapshot,runner=provider_runner)
                except FabricTopologyRuntimeError as exc:
                    raise NvidiaRuntimeError(f"physical GPU/NIC/RDMA topology verification failed: {exc}") from exc
            path_evidence=runtime.validate_nccl_transport_against_rdma(
                stdout+"\n"+stderr,
                rdma_evidence or {},
                gpu_uuid=str(binding["gpu_uuid"]),
                gpu_nic_locality=gpu_nic_locality,
                require_gpu_direct_rdma=int(plan["nnodes"]) > 1 and str(probe.get("network_transport") or "").strip().upper() == "IB",
            ) if int(plan["nnodes"])>1 else {"rdma_devices":(),"verified_rdma_devices":()}
            process_evidence.append({"rank":int(binding["rank"]),"local_rank":int(binding["local_rank"]),"gpu_binding":dict(binding),"probe":probe,"network_transport":probe.get("network_transport"),"gpu_direct_rdma":probe.get("gpu_direct_rdma"),"network_evidence_lines":list(probe.get("network_evidence_lines") or ()),"peer_connections":list(probe.get("peer_connections") or ()),"rdma_devices":list(path_evidence.get("rdma_devices") or ()),"verified_rdma_devices":list(path_evidence.get("verified_rdma_devices") or ()),"hca_selections":list(path_evidence.get("hca_selections") or ()),"verified_hca_selections":list(path_evidence.get("verified_hca_selections") or ()),"verified_rdma_links":list(path_evidence.get("verified_rdma_links") or ()),"gpu_nic_locality":path_evidence.get("gpu_nic_locality"),"physical_fabric_topology":physical_topology,"stdout":stdout[-4000:]})
        if failures: raise NvidiaRuntimeError("distributed NCCL launch failed: "+"; ".join(failures))
        if len(process_evidence)!=len(normalized_bindings): raise NvidiaRuntimeError(f"distributed NCCL execution produced {len(process_evidence)} verified local ranks; expected {len(normalized_bindings)}")
        evidence={"verified":True,"backend":"nccl","collective":"all_reduce","local_runtime":local,"gpu_identity":gpu_identity,"gpu_bindings":normalized_bindings,"process_evidence":process_evidence,"physical_fabric_topology":physical_topology,"attempt_id":attempt_id,"generation":generation,"worker_id":client.worker_id,"node_rank":int(participant["node_rank"]),"world_size":world_size,"nnodes":int(plan["nnodes"]),"command":list(command),"rendezvous_endpoint":plan["rendezvous_endpoint"]}
        if not client.fabric_record_verification(attempt_id,generation,lease_token,evidence).get("ok",True): raise ComputeWorkerError("coordinator rejected execution verification")
        deadline=time.monotonic()+convergence_timeout_seconds; convergence=client.fabric_converge(attempt_id,generation,lease_token)
        while convergence.get("converged") is not True and time.monotonic()<deadline:
            if heartbeat_failed.is_set(): raise ComputeWorkerError(f"execution heartbeat failed: {heartbeat_error[-1]}")
            if stop_heartbeat.wait(min(heartbeat_seconds,1.0)): break
            convergence=client.fabric_converge(attempt_id,generation,lease_token)
        if convergence.get("converged") is not True: raise ComputeWorkerError(f"distributed execution did not converge: {convergence.get('reason','unknown')}")
        evidence["convergence"]=convergence; return evidence
    except Exception as error:
        try: client.fabric_state(attempt_id,generation,lease_token,"failed",str(error))
        except Exception: pass
        raise
    finally:
        stop_processes(); stop_heartbeat.set()
        if thread.is_alive(): thread.join(timeout=2)


def run_integrated_fabric_execution(
    client: ComputeWorkerClient,
    assignment: Mapping[str, Any],
    *,
    rendezvous_endpoint: str,
    heartbeat_seconds: float = 15.0,
) -> Dict[str, Any]:
    """Execute every non-NCCL fabric mode through the common GPU evidence boundary."""
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    attempt_id = str(assignment["attempt_id"])
    generation = int(assignment["generation"])
    lease_token = str(assignment["lease_token"])
    payload = assignment.get("payload")
    allocation = assignment.get("physical_allocation")
    if not isinstance(payload, Mapping) or not isinstance(allocation, Mapping):
        raise ComputeWorkerError("integrated fabric execution requires payload and physical allocation")
    launch = client.fabric_launch_plan(attempt_id, generation, lease_token, rendezvous_endpoint)
    execution = launch.get("execution") if isinstance(launch.get("execution"), dict) else {}
    mode = str(execution.get("mode") or payload.get("execution_mode") or "").strip()
    if not mode:
        raise ComputeWorkerError("launch plan did not declare an execution mode")
    if mode == "nccl":
        return run_fabric_verification(client, assignment, rendezvous_endpoint=rendezvous_endpoint, heartbeat_seconds=heartbeat_seconds)
    participant = next((item for item in launch.get("workers", ()) if item.get("worker_id") == client.worker_id), None)
    if not isinstance(participant, Mapping):
        raise ComputeWorkerError("worker is not present in the integrated execution plan")
    bindings = participant.get("gpu_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ComputeWorkerError("integrated execution plan has no GPU bindings")
    command = payload.get("command")
    if not isinstance(command, (list, tuple)) or not command or any(not str(item).strip() for item in command):
        raise ComputeWorkerError("integrated fabric workload command must be a non-empty argument list")
    command = tuple(str(item) for item in command)
    runtime = NvidiaRuntime()
    try:
        identity = runtime.verify_gpu_bindings(bindings)
    except Exception as exc:
        raise ComputeWorkerError(f"integrated execution GPU identity verification failed: {exc}") from exc

    def run(args, env=None, timeout=None):
        try:
            completed = subprocess.run(list(args), capture_output=True, text=True, env=None if env is None else dict(env), timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ComputeWorkerError(f"integrated execution command failed: {exc}") from exc
        return completed.returncode, completed.stdout, completed.stderr

    probe_evidence = []
    for binding in identity["gpu_bindings"]:
        probe_env = os.environ.copy()
        probe_env["CUDA_VISIBLE_DEVICES"] = str(binding["gpu_id"])
        probe_env["THORIO_EXPECTED_GPU_UUID"] = str(binding["gpu_uuid"])
        rc, stdout, stderr = run(("python", "-m", "lead_engine.gpu_execution_probe", "--expected-gpu-uuid", str(binding["gpu_uuid"])), probe_env, 60.0)
        if int(rc) != 0:
            raise ComputeWorkerError(f"integrated physical GPU probe failed for {binding['gpu_uuid']}: {(stderr or stdout)[-4000:]}")
        marker = "THORIO_GPU_EXECUTION_PROBE_OK "
        line = next((line[len(marker):].strip() for line in str(stdout).splitlines() if line.startswith(marker)), "")
        if not line:
            raise ComputeWorkerError("integrated physical GPU probe returned no evidence marker")
        try:
            evidence = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComputeWorkerError("integrated physical GPU probe returned invalid JSON") from exc
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            raise ComputeWorkerError("integrated physical GPU probe did not verify execution")
        probe_evidence.append(evidence)

    endpoint = str(launch["rendezvous_endpoint"]).strip()
    master_addr, master_port_text = endpoint.rsplit(":", 1)
    master_port = int(master_port_text)
    world_size = int(launch["world_size"])
    base_environment = {
        "MASTER_ADDR": master_addr,
        "MASTER_PORT": str(master_port),
        "WORLD_SIZE": str(world_size),
        "LOCAL_WORLD_SIZE": str(len(bindings)),
        "THORIO_EXECUTION_MODE": mode,
        "THORIO_EXECUTION_PLAN": json.dumps(execution, ensure_ascii=True, sort_keys=True),
        "THORIO_FABRIC_ATTEMPT_ID": attempt_id,
        "THORIO_FABRIC_GENERATION": str(generation),
    }
    client.fabric_state(attempt_id, generation, lease_token, "launching")
    processes = []
    started_at = time.time()
    heartbeat_stop = threading.Event()
    heartbeat_error = []

    def beat():
        while not heartbeat_stop.wait(heartbeat_seconds):
            try:
                response = client.fabric_heartbeat(attempt_id, generation, lease_token)
                if response.get("ok") is not True:
                    heartbeat_error.append("coordinator rejected integrated execution heartbeat")
                    return
            except Exception as exc:
                heartbeat_error.append(str(exc))
                return

    heartbeat_thread = threading.Thread(target=beat, daemon=True)
    heartbeat_thread.start()
    try:
        for binding in sorted(bindings, key=lambda item: int(item["rank"])):
            env = os.environ.copy()
            env.update(base_environment)
            env["RANK"] = str(binding["rank"])
            env["LOCAL_RANK"] = str(binding["local_rank"])
            env["CUDA_VISIBLE_DEVICES"] = str(binding.get("device_id") or str(binding["gpu_id"]).removeprefix("gpu-"))
            env["THORIO_EXPECTED_GPU_UUID"] = str(binding["gpu_uuid"])
            if checkpoint_path:
                env["THORIO_CHECKPOINT_PATH"] = str(checkpoint_path).replace("{rank}", str(binding["rank"]))
            process = subprocess.Popen(list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=(os.name == "posix"))
            processes.append((binding, process))
        client.fabric_state(attempt_id, generation, lease_token, "active")
        results = []
        timeout = payload.get("timeout_seconds")
        timeout_seconds = float(timeout) if timeout is not None else None
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        for binding, process in processes:
            remaining = None if deadline is None else max(0.1, deadline - time.monotonic())
            try:
                stdout, stderr = process.communicate(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise ComputeWorkerError(f"integrated execution rank {binding['rank']} timed out")
            results.append({"rank": int(binding["rank"]), "gpu_uuid": str(binding["gpu_uuid"]), "return_code": int(process.returncode), "stdout": str(stdout)[-8000:], "stderr": str(stderr)[-8000:]})
        if heartbeat_error:
            raise ComputeWorkerError(heartbeat_error[-1])
        failures = [item for item in results if item["return_code"] != 0]
        if failures:
            raise ComputeWorkerError("integrated execution failed: " + "; ".join(f"rank {item['rank']}: {item['stderr'] or item['stdout']}"[-2000:] for item in failures))
        finished_at = time.time()
        artifact_refs = []
        artifact_paths = list(payload.get("output_artifacts") or ())
        checkpoint_path = payload.get("checkpoint_path")
        if checkpoint_path:
            artifact_paths.append(checkpoint_path)
        seen_artifacts = set()
        ranks = sorted({int(item["rank"]) for item in results}) or [0]
        for rank in ranks:
            for raw_path in artifact_paths:
                path = Path(str(raw_path).replace("{rank}", str(rank)))
                if str(path) in seen_artifacts or not path.exists() or not path.is_file():
                    continue
                seen_artifacts.add(str(path))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                artifact_refs.append({
                    "path": str(path),
                    "sha256": digest,
                    "size_bytes": path.stat().st_size,
                    "rank": rank,
                })
        mode_details = execution.get("mode_details") if isinstance(execution.get("mode_details"), dict) else {}
        matrix_evidence = {
            "physical_gpu_execution": bool(probe_evidence),
            "execution_identity": bool(attempt_id and generation > 0 and client.worker_id and execution.get("plan_id")),
            "model_partition_plan": "model_partition_plan" in mode_details,
            "tensor_shard_plan": "tensor_shard_plan" in mode_details,
            "context_partition_plan": "context_partition_plan" in mode_details,
            "expert_placement_plan": "expert_parallel_plan" in mode_details,
            "state_shard_plan": "sharded_state_plan" in mode_details,
            "checkpoint_compatible": bool(
                isinstance(mode_details.get("sharded_state_plan"), dict)
                and mode_details["sharded_state_plan"].get("checkpoint_compatible") is True
            ),
            "hybrid_plan": "hybrid_execution_plan" in mode_details,
            "required_stage_evidence": bool(
                isinstance(mode_details.get("hybrid_execution_plan"), dict)
                and mode_details["hybrid_execution_plan"].get("stages")
            ),
        }
        try:
            fabric_report = FabricVerificationMatrix().evaluate(ExecutionMode(mode), matrix_evidence)
        except ValueError as exc:
            raise ComputeWorkerError(f"integrated execution verification mode is invalid: {exc}") from exc
        verification = {
            "verified": True,
            "execution_kind": "gpu_workload",
            "execution_mode": mode,
            "fabric_verification": {
                "passed": fabric_report.passed,
                "maturity_state": fabric_report.maturity_state,
                "missing": list(fabric_report.missing),
            },
            "execution_plan": execution,
            "attempt_id": attempt_id,
            "generation": generation,
            "task_id": str(assignment.get("task_id") or ""),
            "worker_id": client.worker_id,
            "gpu_bindings": [dict(binding) for binding in bindings],
            "physical_gpu_execution": probe_evidence,
            "process_evidence": results,
            "command": list(command),
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": finished_at - started_at,
            "return_code": 0,
            "artifact_refs": artifact_refs,
        }
        response = client.gpu_record_verification(attempt_id, generation, lease_token, verification)
        if response.get("ok", True) is not True:
            raise ComputeWorkerError("coordinator rejected integrated GPU execution evidence")
        deadline = time.monotonic() + max(60.0, heartbeat_seconds * 4)
        convergence = client.fabric_converge(attempt_id, generation, lease_token)
        while convergence.get("converged") is not True and time.monotonic() < deadline:
            if heartbeat_error:
                raise ComputeWorkerError(heartbeat_error[-1])
            if heartbeat_stop.wait(min(heartbeat_seconds, 1.0)):
                break
            convergence = client.fabric_converge(attempt_id, generation, lease_token)
        if convergence.get("converged") is not True:
            raise ComputeWorkerError(f"integrated execution did not converge: {convergence.get('reason', 'unknown')}")
        verification["convergence"] = convergence
        return verification
    except Exception as exc:
        for _, process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass
        try:
            client.fabric_state(attempt_id, generation, lease_token, "failed", str(exc))
        except Exception:
            pass
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=max(1.0, heartbeat_seconds))

def run_worker(client: ComputeWorkerClient, *, idle_seconds: float = 2.0, heartbeat_seconds: float = 15.0, fabric_rendezvous_endpoint: str | None = None, stop_event=None) -> None:
    if idle_seconds <= 0 or heartbeat_seconds <= 0: raise ValueError("worker intervals must be positive")
    stop_event=stop_event or _NeverStop(); fabric_rendezvous_endpoint=(fabric_rendezvous_endpoint or os.environ.get("THORIO_FABRIC_RENDEZVOUS_ENDPOINT","")).strip(); backoff=1.0; last_heartbeat=0.0
    while not stop_event.is_set():
        try:
            if not client._registered: client.register()
            now=time.monotonic()
            if now-last_heartbeat>=heartbeat_seconds: client.heartbeat(1 if getattr(client,"_active_task",None) else 0); last_heartbeat=now
            assignments=client.fabric_assignments()
            if assignments:
                if not fabric_rendezvous_endpoint:
                    for assignment in assignments:
                        response=client.fabric_state(str(assignment["attempt_id"]),int(assignment["generation"]),str(assignment["lease_token"]),"failed","THORIO_FABRIC_RENDEZVOUS_ENDPOINT is required for fabric execution")
                        if response.get("ok") is not True: raise ComputeWorkerError("coordinator rejected fabric failure state")
                else:
                    for assignment in assignments:
                        try:
                            mode = str((assignment.get("payload") or {}).get("execution_mode") or "").strip()
                            if mode in {"", "nccl"}:
                                run_fabric_verification(client, assignment, rendezvous_endpoint=fabric_rendezvous_endpoint)
                            else:
                                run_integrated_fabric_execution(client, assignment, rendezvous_endpoint=fabric_rendezvous_endpoint, heartbeat_seconds=heartbeat_seconds)
                        except NvidiaRuntimeError:
                            if stop_event.wait(idle_seconds): break
                backoff=1.0; continue
            task=client.claim(); backoff=1.0
        except ComputeWorkerError:
            client._registered=False
            if stop_event.wait(backoff): break
            backoff=min(30.0,backoff*2.0); continue
        if task is None:
            stop_event.wait(idle_seconds); continue
        client._active_task=task["task_id"]
        try:
            payload=task["payload"]
            kind=str(payload.get("kind") or "").strip()
            if ("compute_requirements" in payload or kind == "gpu_workload") and not isinstance(task.get("physical_allocation"),Mapping):
                raise ComputeWorkerError("coordinator did not assign a physical execution allocation")
            if kind == "gpu_workload":
                result=execute_gpu_workload(client,task,heartbeat_seconds=heartbeat_seconds)
            else:
                result=execute_checkpointed_lead_prepare(client,task["task_id"],task["lease_token"],payload) if kind=="lead_prepare" else execute_compute_task(payload)
            client.complete(task["task_id"],task["lease_token"],result)
        except Exception as error:
            try: client.release(task["task_id"],task["lease_token"],str(error))
            except ComputeWorkerError: client._registered=False
        finally: client._active_task=None


class _NeverStop:
    def is_set(self) -> bool: return False
    def wait(self, seconds: float) -> bool: time.sleep(seconds); return False


def client_from_environment() -> ComputeWorkerClient:
    url=os.environ.get("THORIO_COMPUTE_COORDINATOR_URL",""); token=os.environ.get("THORIO_COMPUTE_AUTH_TOKEN",""); worker_id=os.environ.get("THORIO_WORKER_ID","") or local_worker_identity().worker_id
    if not url: raise RuntimeError("THORIO_COMPUTE_COORDINATOR_URL is required")
    if not token: raise RuntimeError("THORIO_COMPUTE_AUTH_TOKEN is required")
    return ComputeWorkerClient(url,token,worker_id,int(os.environ.get("THORIO_COMPUTE_HTTP_TIMEOUT","20")))


if __name__ == "__main__": run_worker(client_from_environment())