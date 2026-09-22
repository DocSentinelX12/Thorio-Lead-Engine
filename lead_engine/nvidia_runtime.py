"""Evidence-backed NVIDIA CUDA/NCCL execution runtime boundary.

This module never simulates accelerator capability. Verification succeeds only
when the local host exposes real NVIDIA tooling and an installed NCCL library.
Distributed verification invokes a real torchrun NCCL all-reduce probe.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


class NvidiaRuntimeError(RuntimeError):
    """Raised when required NVIDIA CUDA/NCCL runtime evidence is unavailable."""


@dataclass(frozen=True)
class NvidiaRuntime:
    runner: Callable[[Sequence[str], float], tuple[int, str, str]] | None = None
    which: Callable[[str], str | None] = shutil.which
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _run(self, args: Sequence[str]) -> tuple[int, str, str]:
        try:
            if self.runner is not None:
                return self.runner(args, self.timeout_seconds)
            result = subprocess.run(list(args), capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
            return result.returncode, result.stdout, result.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NvidiaRuntimeError(f"runtime probe failed for {args[0]}: {exc}") from exc

    def _required_command(self, name: str) -> str:
        path = self.which(name)
        if not path:
            raise NvidiaRuntimeError(f"{name} is required for NVIDIA runtime verification")
        return path

    def verify_local(self) -> dict[str, object]:
        nvidia_smi = self._required_command("nvidia-smi")
        nvcc = self._required_command("nvcc")
        ldconfig = self._required_command("ldconfig")
        rc, stdout, stderr = self._run((nvidia_smi, "-L"))
        if rc != 0:
            raise NvidiaRuntimeError(f"nvidia-smi GPU enumeration failed: {(stderr or stdout).strip()[:1000]}")
        gpu_lines = [line.strip() for line in stdout.splitlines() if line.strip().startswith("GPU ")]
        if not gpu_lines:
            raise NvidiaRuntimeError("nvidia-smi reported no physical NVIDIA GPUs")
        rc, stdout, stderr = self._run((nvcc, "--version"))
        if rc != 0:
            raise NvidiaRuntimeError(f"nvcc verification failed: {(stderr or stdout).strip()[:1000]}")
        match = re.search(r"release\s+([0-9]+(?:\.[0-9]+)+)", stdout + "\n" + stderr, re.IGNORECASE)
        if not match:
            raise NvidiaRuntimeError("nvcc did not report a CUDA toolkit release")
        cuda_version = match.group(1)
        rc, stdout, stderr = self._run((ldconfig, "-p"))
        if rc != 0:
            raise NvidiaRuntimeError(f"ldconfig verification failed: {(stderr or stdout).strip()[:1000]}")
        nccl_lines = [line.strip() for line in stdout.splitlines() if re.search(r"libnccl\.so(?:\.|\s|$)", line)]
        if not nccl_lines:
            raise NvidiaRuntimeError("NCCL library was not found in the system linker cache")
        nccl_match = re.search(r"=>\s*(\S+libnccl\.so(?:\.[0-9]+)*)\s*$", nccl_lines[0])
        nccl_library = nccl_match.group(1) if nccl_match else nccl_lines[0]
        return {"verified": True, "gpu_count": len(gpu_lines), "gpu_enumeration": tuple(gpu_lines), "cuda_toolkit_version": cuda_version, "nccl_library": nccl_library, "evidence_source": ("nvidia-smi", "nvcc", "ldconfig")}

    def verify_gpu_bindings(self, gpu_bindings: Sequence[Mapping[str, object]]) -> dict[str, object]:
        if not gpu_bindings:
            raise NvidiaRuntimeError("at least one GPU binding is required")
        nvidia_smi = self._required_command("nvidia-smi")
        rc, stdout, stderr = self._run((nvidia_smi, "--query-gpu=index,uuid", "--format=csv,noheader,nounits"))
        if rc != 0:
            raise NvidiaRuntimeError(f"nvidia-smi GPU identity verification failed: {(stderr or stdout).strip()[:1000]}")
        observed = {}
        for line in stdout.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                observed[parts[0]] = parts[1]
        expected = {}
        for binding in gpu_bindings:
            gpu_id = str(binding.get("gpu_id") or "").strip()
            gpu_uuid = str(binding.get("gpu_uuid") or "").strip()
            device_id = gpu_id if gpu_id.isdigit() else gpu_id.removeprefix("gpu-")
            if not device_id.isdigit() or not gpu_uuid:
                raise NvidiaRuntimeError(f"invalid allocated GPU identity: {gpu_id}/{gpu_uuid}")
            if device_id in expected:
                raise NvidiaRuntimeError(f"duplicate allocated NVIDIA device index: {device_id}")
            expected[device_id] = gpu_uuid
        mismatches = [f"{gpu_id}: expected {gpu_uuid}, observed {observed.get(gpu_id, '<missing>')}" for gpu_id, gpu_uuid in expected.items() if observed.get(gpu_id) != gpu_uuid]
        if mismatches:
            raise NvidiaRuntimeError("allocated NVIDIA GPU identity verification failed: " + "; ".join(mismatches))
        return {"verified": True, "gpu_bindings": [dict(binding) for binding in gpu_bindings]}

    def distributed_process_command(self) -> tuple[str, ...]:
        python = sys.executable
        if not python:
            raise NvidiaRuntimeError("current Python executable is required for distributed NVIDIA verification")
        return (python, "-m", "lead_engine.nccl_all_reduce_probe")

    def distributed_command(self, *, world_size: int, node_rank: int, nnodes: int, master_addr: str, master_port: int, rendezvous_id: str | None = None, process_count: int | None = None) -> tuple[str, ...]:
        if world_size < 2:
            raise ValueError("world_size must be at least 2 for distributed NCCL verification")
        if nnodes < 1 or not 0 <= node_rank < nnodes:
            raise ValueError("node_rank must be within nnodes")
        if world_size % nnodes != 0:
            raise ValueError("world_size must divide evenly across nnodes")
        resolved_process_count = process_count if process_count is not None else world_size // nnodes
        if resolved_process_count < 1 or resolved_process_count * nnodes != world_size:
            raise ValueError("process_count must multiply by nnodes to equal world_size")
        if not master_addr.strip():
            raise ValueError("master_addr is required")
        if not 1 <= master_port <= 65535:
            raise ValueError("master_port must be between 1 and 65535")
        torchrun = self._required_command("torchrun")
        command = [torchrun, f"--nproc-per-node={resolved_process_count}", f"--nnodes={nnodes}", f"--node-rank={node_rank}", f"--master-addr={master_addr.strip()}", f"--master-port={master_port}"]
        if rendezvous_id:
            command.extend(["--rdzv-id", rendezvous_id, "--rdzv-backend", "c10d", "--rdzv-endpoint", f"{master_addr.strip()}:{master_port}"])
        command.extend(["-m", "lead_engine.nccl_all_reduce_probe"])
        return tuple(command)

    @staticmethod
    def parse_nccl_network_evidence(log_output: str) -> dict[str, object]:
        if not isinstance(log_output, str):
            raise NvidiaRuntimeError("NCCL process log output must be text")
        transports = []
        hca_selections = []
        peer_connections = []
        evidence_lines = []
        gpu_direct_rdma = False
        for raw_line in log_output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.search(r"NCCL INFO Using network ([A-Za-z0-9_.-]+)", line, re.IGNORECASE)
            if match:
                transports.append(match.group(1)); evidence_lines.append(line[-1000:])
            match = re.search(r"NCCL INFO NET/([A-Za-z0-9_.-]+)\s*:\s*Using\b", line, re.IGNORECASE)
            if match:
                transport = match.group(1); transports.append(transport)
                hca_match = re.search(r"\b(mlx[45]_[A-Za-z0-9_.-]+):(\d+)\/(?:IB|RoCE)\b", line, re.IGNORECASE)
                if hca_match:
                    hca_selections.append({"device": hca_match.group(1), "port": int(hca_match.group(2)), "transport": transport})
                evidence_lines.append(line[-1000:])
            channel_match = re.search(r"NCCL INFO Channel\s+([^\s:]+)\s*:\s*(\d+)\[(\d+)\]\s*->\s*(\d+)\[(\d+)\](?:\s+\[(send|recv)\])?\s+via\s+NET/([^\s]+)", line, re.IGNORECASE)
            if channel_match:
                peer_connections.append({"channel": channel_match.group(1), "local_rank": int(channel_match.group(2)), "peer_rank": int(channel_match.group(4)), "direction": (channel_match.group(6) or "unknown").lower(), "transport": channel_match.group(7)})
                evidence_lines.append(line[-1000:])
            if re.search(r"GPU Direct RDMA Enabled", line, re.IGNORECASE) or re.search(r"GDRDMA", line, re.IGNORECASE):
                gpu_direct_rdma = True; evidence_lines.append(line[-1000:])
        unique_transports = tuple(sorted({transport.strip() for transport in transports if transport.strip()}))
        if len(unique_transports) > 1:
            raise NvidiaRuntimeError("NCCL reported multiple network transports for one rank: " + ", ".join(unique_transports))
        return {"network_transport": unique_transports[0] if unique_transports else None, "hca_selections": tuple(dict(items) for items in sorted({tuple(sorted(item.items())) for item in hca_selections})), "peer_connections": tuple(peer_connections), "network_evidence_lines": tuple(evidence_lines[-8:]), "gpu_direct_rdma": gpu_direct_rdma}

    @classmethod
    def validate_nccl_transport_against_rdma(cls, log_output: str, rdma_evidence: Mapping[str, object], *, gpu_uuid: str | None = None, gpu_nic_locality: Sequence[Mapping[str, object]] | None = None) -> dict[str, object]:
        network = cls.parse_nccl_network_evidence(log_output)
        devices = rdma_evidence.get("devices") if isinstance(rdma_evidence, Mapping) else None
        if not isinstance(devices, list):
            raise NvidiaRuntimeError("RDMA evidence does not contain a device inventory")
        rdma_devices = tuple(sorted({str(item.get("device") or "").strip() for item in devices if isinstance(item, Mapping) and str(item.get("device") or "").strip()}))
        if network["network_transport"] == "IB":
            selections = tuple(network.get("hca_selections") or ())
            if not selections:
                raise NvidiaRuntimeError("NCCL selected IB but did not expose an RDMA device and port in its network evidence")
            used_devices = tuple(sorted({str(item.get("device") or "").strip() for item in selections if isinstance(item, Mapping)}))
            missing_devices = tuple(device for device in used_devices if device not in rdma_devices)
            if not used_devices or missing_devices:
                raise NvidiaRuntimeError("NCCL selected RDMA devices absent from verified host RDMA inventory: " + ", ".join(missing_devices))
            verified_selections = []; verified_links = []
            links = rdma_evidence.get("links", ()) if isinstance(rdma_evidence, Mapping) else ()
            for selection in selections:
                device = str(selection.get("device") or "").strip(); port = int(selection.get("port"))
                matching_links = [link for link in links if isinstance(link, Mapping) and str(link.get("rdma_device") or "").strip() == device and int(link.get("port") or -1) == port]
                if not matching_links:
                    raise NvidiaRuntimeError(f"RDMA port {device}:{port} selected by NCCL is not present in verified RDMA link evidence")
                if not any(
                    str(link.get("state") or "").strip().upper() == "ACTIVE"
                    and str(link.get("physical_state") or "").strip().upper() in {"LINK_UP", "LINK_ACTIVE"}
                    for link in matching_links
                ):
                    raise NvidiaRuntimeError(f"RDMA port {device}:{port} is not active in verified physical link evidence")
                matching_links = [
                    link for link in matching_links
                    if str(link.get("state") or "").strip().upper() == "ACTIVE"
                    and str(link.get("physical_state") or "").strip().upper() in {"LINK_UP", "LINK_ACTIVE"}
                ]
                for link in matching_links:
                    verified_links.append({"rdma_device": device, "port": port, "netdev": link.get("netdev"), "pci_bus_id": link.get("pci_bus_id"), "state": link.get("state"), "physical_state": link.get("physical_state"), "link_layer": link.get("link_layer"), "gids": list(link.get("gids") or ())})
                verified_selections.append(dict(selection))
            verified = tuple(sorted(used_devices))
        else:
            used_devices = (); verified = (); verified_selections = []; verified_links = []
        locality_evidence = None
        if network["network_transport"] == "IB" and gpu_uuid is not None:
            locality_rows = [row for row in (gpu_nic_locality or ()) if isinstance(row, Mapping) and str(row.get("gpu_uuid") or "").strip() == gpu_uuid]
            matched = []
            for row in locality_rows:
                nic = str(row.get("nic") or "").strip(); nic_pci = str(row.get("nic_pci_bus_id") or "").strip()
                for link in rdma_evidence.get("links", ()) if isinstance(rdma_evidence, Mapping) else ():
                    if isinstance(link, Mapping) and str(link.get("rdma_device") or "").strip() in verified and (str(link.get("netdev") or "").strip() == nic or str(link.get("pci_bus_id") or "").strip() == nic_pci):
                        matched.append({**dict(row), "rdma_device": str(link.get("rdma_device")), "rdma_port": link.get("port"), "rdma_pci_bus_id": link.get("pci_bus_id"), "link_layer": link.get("link_layer")})
            if not matched:
                raise NvidiaRuntimeError(f"NCCL IB device is not reconciled to verified NIC locality for GPU {gpu_uuid}")
            locality_evidence = matched[0]
        return {**network, "rdma_devices": rdma_devices, "verified_rdma_devices": verified, "verified_hca_selections": tuple(verified_selections) if network["network_transport"] == "IB" else (), "verified_rdma_links": tuple(verified_links) if network["network_transport"] == "IB" else (), "gpu_nic_locality": locality_evidence}

    @staticmethod
    def reconcile_planned_physical_path(
        planned_path: Mapping[str, object],
        actual_evidence: Mapping[str, object],
    ) -> dict[str, object]:
        """Require the scheduler's physical GPU/NIC/RDMA path to match execution."""
        if not isinstance(planned_path, Mapping) or not isinstance(actual_evidence, Mapping):
            raise NvidiaRuntimeError("planned physical path evidence must be objects")
        planned_gpu = str(planned_path.get("gpu_uuid") or "").strip()
        locality = actual_evidence.get("gpu_nic_locality")
        selections = actual_evidence.get("verified_hca_selections")
        if not planned_gpu or not isinstance(locality, Mapping) or not isinstance(selections, list):
            raise NvidiaRuntimeError("planned physical path cannot be reconciled with execution evidence")
        actual_gpu = str(locality.get("gpu_uuid") or "").strip()
        fields = (
            "gpu_uuid", "nic", "nic_pci_bus_id", "rdma_device",
            "rdma_port", "rdma_pci_bus_id", "link_layer",
        )
        for field in fields:
            expected = planned_gpu if field == "gpu_uuid" else planned_path.get(field)
            observed = actual_gpu if field == "gpu_uuid" else locality.get(field)
            if expected is not None and str(expected).strip() != str(observed).strip():
                raise NvidiaRuntimeError(
                    f"planned physical path mismatch for {field}: "
                    f"planned={expected!r} observed={observed!r}"
                )
        device = str(planned_path.get("rdma_device") or "").strip()
        port = planned_path.get("rdma_port")
        if not any(
            isinstance(selection, Mapping)
            and str(selection.get("device") or "").strip() == device
            and selection.get("port") == port
            and str(selection.get("transport") or "").strip().upper() == "IB"
            for selection in selections
        ):
            raise NvidiaRuntimeError(
                f"planned physical path does not match NCCL-selected HCA port: {device}:{port}"
            )
        return {
            "verified": True,
            "gpu_uuid": planned_gpu,
            "nic": str(planned_path.get("nic") or "").strip(),
            "rdma_device": device,
            "rdma_port": port,
            "link_layer": str(planned_path.get("link_layer") or "").strip(),
        }

    @staticmethod
    def reconcile_distributed_network_paths(process_evidence: Sequence[Mapping[str, object]], *, world_size: int, nnodes: int) -> dict[str, object]:
        if world_size < 2: raise ValueError("world_size must be at least 2")
        if nnodes < 1: raise ValueError("nnodes must be at least 1")
        if not isinstance(process_evidence, Sequence) or isinstance(process_evidence, (str, bytes)): raise NvidiaRuntimeError("distributed process evidence must be a sequence")
        if len(process_evidence) != world_size: raise NvidiaRuntimeError(f"distributed network reconciliation received {len(process_evidence)} ranks; expected {world_size}")
        rank_keys=set(); transports=set(); paths=[]
        for item in process_evidence:
            if not isinstance(item, Mapping): raise NvidiaRuntimeError("distributed process evidence contains a non-object")
            try: rank=int(item.get("rank", -1))
            except (TypeError, ValueError): raise NvidiaRuntimeError("distributed process evidence contains an invalid rank")
            if not 0 <= rank < world_size: raise NvidiaRuntimeError(f"distributed process evidence rank {rank} is outside world size")
            gpu_binding=item.get("gpu_binding")
            if not isinstance(gpu_binding, Mapping): raise NvidiaRuntimeError(f"rank {rank} is missing its exact GPU binding")
            gpu_uuid=str(gpu_binding.get("gpu_uuid") or "").strip()
            if not gpu_uuid: raise NvidiaRuntimeError(f"rank {rank} is missing its GPU UUID")
            key=(rank,gpu_uuid)
            if key in rank_keys or any(existing_rank == rank for existing_rank,_ in rank_keys): raise NvidiaRuntimeError(f"duplicate distributed rank evidence: {rank}")
            if any(existing_uuid == gpu_uuid for _,existing_uuid in rank_keys): raise NvidiaRuntimeError(f"GPU UUID {gpu_uuid} is claimed by multiple distributed ranks")
            rank_keys.add(key)
            probe=item.get("probe")
            if not isinstance(probe, Mapping): raise NvidiaRuntimeError(f"rank {rank} is missing NCCL probe evidence")
            if int(probe.get("rank",-1)) != rank or str(probe.get("gpu_uuid") or "").strip() != gpu_uuid: raise NvidiaRuntimeError(f"rank {rank} NCCL probe does not match its allocated GPU identity")
            if int(probe.get("world_size",-1)) != world_size: raise NvidiaRuntimeError(f"rank {rank} NCCL probe world size does not match the launch contract")
            transport=str(item.get("network_transport") or probe.get("network_transport") or "").strip().upper()
            if nnodes > 1 and not transport: raise NvidiaRuntimeError(f"rank {rank} has no verified NCCL network transport")
            if transport: transports.add(transport)
            peer_connections=[dict(edge) for edge in item.get("peer_connections", ()) if isinstance(edge, Mapping)]
            if transport == "IB":
                selections=item.get("hca_selections"); verified_selections=item.get("verified_hca_selections"); rdma_devices=item.get("rdma_devices"); verified_devices=item.get("verified_rdma_devices"); verified_links=item.get("verified_rdma_links"); locality=item.get("gpu_nic_locality")
                if not isinstance(selections,list) or not selections or not isinstance(verified_selections,list) or verified_selections != selections or not isinstance(rdma_devices,list) or not rdma_devices or not isinstance(verified_devices,list) or sorted(set(str(device).strip() for device in verified_devices)) != sorted(set(str(device).strip() for device in rdma_devices)) or not isinstance(verified_links,list) or not verified_links or not isinstance(locality,Mapping): raise NvidiaRuntimeError(f"rank {rank} has incomplete verified IB path evidence")
                locality_device=str(locality.get("rdma_device") or "").strip(); locality_port=locality.get("rdma_port")
                if not locality_device or not isinstance(locality_port,int): raise NvidiaRuntimeError(f"rank {rank} has incomplete GPU-to-RDMA locality evidence")
                if not any(isinstance(s,Mapping) and str(s.get("device") or "").strip()==locality_device and s.get("port")==locality_port and str(s.get("transport") or "").strip().upper()=="IB" for s in verified_selections): raise NvidiaRuntimeError(f"rank {rank} GPU locality does not match its NCCL-selected HCA port")
                if not any(isinstance(link,Mapping) and str(link.get("rdma_device") or "").strip()==locality_device and link.get("port")==locality_port and str(link.get("link_layer") or "").strip() for link in verified_links): raise NvidiaRuntimeError(f"rank {rank} NCCL-selected HCA port lacks verified physical RDMA link identity")
                paths.append({"rank":rank,"gpu_uuid":gpu_uuid,"network_transport":transport,"hca_selections":[dict(s) for s in selections if isinstance(s,Mapping)],"verified_rdma_links":[dict(link) for link in verified_links if isinstance(link,Mapping)],"peer_connections":peer_connections,"rdma_device":locality_device,"rdma_port":locality_port,"link_layer":locality.get("link_layer")})
            else:
                paths.append({"rank":rank,"gpu_uuid":gpu_uuid,"network_transport":transport or None,"peer_connections":peer_connections})
        if nnodes > 1 and len(transports) != 1: raise NvidiaRuntimeError("distributed ranks selected inconsistent NCCL network transports: " + ", ".join(sorted(transports)))
        if sorted(rank for rank,_ in rank_keys) != list(range(world_size)): raise NvidiaRuntimeError("distributed network evidence does not cover every global rank")
        return {"verified":True,"world_size":world_size,"nnodes":nnodes,"network_transport":next(iter(transports)) if len(transports)==1 else None,"rank_paths":sorted(paths,key=lambda item:int(item["rank"]))}

    @staticmethod
    def validate_distributed_probe_output(stdout: str, world_size: int, *, expected_rank: int | None = None, expected_gpu_uuid: str | None = None, log_output: str | None = None) -> dict[str, object]:
        if world_size < 2: raise ValueError("world_size must be at least 2")
        marker="THORIO_NCCL_PROBE_OK "; lines=[line.strip() for line in stdout.splitlines() if line.strip().startswith(marker)]
        if not lines: raise NvidiaRuntimeError("distributed NCCL probe completed without verified success evidence")
        try: probe=json.loads(lines[-1][len(marker):])
        except json.JSONDecodeError as exc: raise NvidiaRuntimeError("distributed NCCL probe emitted invalid success evidence") from exc
        expected_sum=world_size*(world_size+1)//2; expected_nnodes=int(probe.get("nnodes",1))
        if expected_nnodes < 1: raise NvidiaRuntimeError("distributed NCCL probe reported an invalid node count")
        if probe.get("backend")!="nccl" or probe.get("collective")!="all_reduce" or probe.get("verified_on_gpu") is not True or int(probe.get("world_size",-1))!=world_size or int(probe.get("expected_sum",-1))!=expected_sum: raise NvidiaRuntimeError("distributed NCCL probe evidence did not verify the requested GPU collective")
        if expected_rank is not None and int(probe.get("rank",-1)) != expected_rank: raise NvidiaRuntimeError(f"distributed NCCL probe rank mismatch: expected {expected_rank}, got {probe.get('rank')}")
        if expected_gpu_uuid is not None and str(probe.get("gpu_uuid") or "").strip()!=expected_gpu_uuid: raise NvidiaRuntimeError("distributed NCCL probe GPU UUID does not match the allocated physical GPU")
        network=NvidiaRuntime.parse_nccl_network_evidence(log_output if log_output is not None else stdout); probe.update(network)
        if expected_nnodes > 1 and not str(probe.get("network_transport") or "").strip(): raise NvidiaRuntimeError("multi-node NCCL execution completed without explicit network transport evidence")
        return probe

    def verify_distributed_nccl(self, *, world_size: int, node_rank: int, nnodes: int, master_addr: str, master_port: int) -> dict[str, object]:
        command=self.distributed_command(world_size=world_size,node_rank=node_rank,nnodes=nnodes,master_addr=master_addr,master_port=master_port)
        if world_size < 2: raise ValueError("world_size must be at least 2")
        rc,stdout,stderr=self._run(command)
        if rc != 0: raise NvidiaRuntimeError(f"distributed NCCL all-reduce probe failed: {(stderr or stdout).strip()[:4000]}")
        marker="THORIO_NCCL_PROBE_OK "; lines=[line.strip() for line in stdout.splitlines() if line.strip().startswith(marker)]
        if not lines: raise NvidiaRuntimeError("distributed NCCL probe completed without verified success evidence")
        try: probe=json.loads(lines[-1][len(marker):])
        except json.JSONDecodeError as exc: raise NvidiaRuntimeError("distributed NCCL probe emitted invalid success evidence") from exc
        probe["nnodes"]=nnodes
        probe=self.validate_distributed_probe_output("THORIO_NCCL_PROBE_OK " + json.dumps(probe,sort_keys=True),world_size,log_output=stdout+"\n"+stderr)
        return {"verified":True,"backend":"nccl","world_size":world_size,"nnodes":nnodes,"node_rank":node_rank,"network_transport":probe["network_transport"],"gpu_direct_rdma":probe["gpu_direct_rdma"],"network_evidence_lines":probe["network_evidence_lines"],"probe_output":probe,"command":command}
