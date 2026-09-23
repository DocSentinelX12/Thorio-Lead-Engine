"""Physical resource scheduler for the additive Thorio compute fabric.

This module schedules execution resources only. It never owns lead, Airtable,
qualification, outreach, revenue, or Partnership state.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from .compute_inventory import ComputeInventory
from .compute_placement import PlacementDecision, PlacementEvaluator
from .compute_fabric_telemetry import physical_path_key, workload_performance_key
from .compute_resources import ComputeRequirements, ResourceState, WorkloadClass


@dataclass(frozen=True)
class ComputeAllocation:
    allocation_id: str
    provider_id: str
    domain_id: str
    node_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    resource_keys: tuple[str, ...]
    capability_evidence: tuple[dict[str, Any], ...]
    placement_id: str | None = None


class ComputeSchedulingError(RuntimeError):
    pass


def _version_tuple(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    parts = []
    for part in value.strip().split("."):
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _version_at_least(actual: str | None, required: str | None) -> bool:
    if required is None:
        return True
    a = _version_tuple(actual)
    r = _version_tuple(required)
    return a is not None and r is not None and a >= r


class ComputeScheduler:
    """Atomically reserves concrete inventory resources for execution."""

    def __init__(self, inventory: ComputeInventory, performance_history_provider=None, route_health_provider=None):
        self.inventory = inventory
        self.performance_history_provider = performance_history_provider
        self.route_health_provider = route_health_provider or getattr(inventory, "fabric_route_health_index", None)

    def placement(self, requirements: ComputeRequirements) -> PlacementDecision:
        """Construct a complete verified placement without reserving resources."""
        if not isinstance(requirements, ComputeRequirements):
            raise TypeError("requirements must be ComputeRequirements")
        evaluator = PlacementEvaluator(
            self,
            requirements,
            self.inventory.eligible(),
            self._performance_history(requirements),
            self._route_health(),
        )
        try:
            placement = evaluator.evaluate()
        except RuntimeError as error:
            self._last_placement_trace = tuple(evaluator.trace)
            raise ComputeSchedulingError(str(error)) from error
        self._last_placement_trace = placement.decision_trace
        return placement

    def _performance_history(self, requirements=None) -> dict[str, dict[str, Any]]:
        if self.performance_history_provider is None:
            return {}
        try:
            value = self.performance_history_provider(requirements)
        except TypeError:
            value = self.performance_history_provider()
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _gpu_performance_key(gpu: dict[str, Any], history: dict[str, dict[str, Any]], requirements=None) -> tuple[int, float, int]:
        payload = json.loads(gpu["payload_json"])
        gpu_uuid = str(payload.get("gpu_uuid") or "").strip()
        paths = ComputeScheduler._verified_gpu_nic_rdma_path(gpu, gpu_uuid)
        import hashlib
        observations = []
        for path in paths:
            identity = {
                str(key): path[key]
                for key in (
                    "node_id", "gpu_uuid", "nic", "nic_pci_bus_id",
                    "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer",
                )
                if path.get(key) is not None and str(path.get(key)).strip() != ""
            }
            if not identity:
                continue
            legacy_key = physical_path_key(identity)
            workload = {}
            if requirements is not None:
                workload = {
                    "workload_class": getattr(getattr(requirements, "workload_class", None), "value", getattr(requirements, "workload_class", None)),
                    **dict(getattr(requirements, "performance_signature", ()) or ()),
                }
            key = workload_performance_key(identity, workload) if workload else legacy_key
            if key in history:
                observations.append(history[key])
            elif legacy_key in history:
                observations.append(history[legacy_key])
        if not observations:
            return (1, float("inf"), 0)
        best = min(
            observations,
            key=lambda item: float(item.get("avg_all_reduce_elapsed_ms", float("inf"))),
        )
        return (
            0,
            float(best.get("avg_all_reduce_elapsed_ms", float("inf"))),
            -int(best.get("sample_count", 0)),
        )

    def _route_health(self) -> dict[str, dict[str, Any]]:
        if self.route_health_provider is None:
            return {}
        value = self.route_health_provider()
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _gpu_route_health_key(
        gpu: dict[str, Any],
        health: dict[str, dict[str, Any]],
    ) -> tuple[int, float, float, float, int]:
        payload = json.loads(gpu["payload_json"])
        paths = ComputeScheduler._verified_gpu_nic_rdma_path(gpu, payload.get("gpu_uuid"))
        observations = []
        for path in paths:
            key = physical_path_key(path)
            if key in health:
                observations.append(health[key])
        if not observations:
            return (1, float("inf"), float("inf"), float("inf"), 0)
        best = min(
            observations,
            key=lambda item: (
                float(item.get("latency_delta_from_mean_ms", float("inf"))),
                float(item.get("failure_rate", float("inf"))),
                float(item.get("latest_latency_ms", float("inf"))),
            ),
        )
        return (
            0,
            float(best.get("latency_delta_from_mean_ms", float("inf"))),
            float(best.get("failure_rate", float("inf"))),
            float(best.get("latest_latency_ms", float("inf"))),
            -int(best.get("sample_count", 0)),
        )

    @staticmethod
    def _gpu_matches(row: dict[str, Any], requirements) -> bool:
        if row.get("resource_type") != "gpu":
            return False
        if row.get("state") not in {ResourceState.HEALTHY.value, ResourceState.AVAILABLE.value}:
            return False
        if row.get("expires_at") is not None:
            import time
            if float(row["expires_at"]) <= time.time():
                return False
        payload = json.loads(row["payload_json"])
        if requirements.min_vram_bytes is not None and (
            payload.get("vram_bytes") is None or int(payload["vram_bytes"]) < requirements.min_vram_bytes
        ):
            return False
        if not _version_at_least(payload.get("compute_capability"), requirements.min_compute_capability):
            return False
        if not _version_at_least(payload.get("cuda_version"), requirements.required_cuda_version):
            return False
        if not _version_at_least(payload.get("driver_version"), requirements.required_driver_version):
            return False
        if requirements.required_nvlink_domain is not None and payload.get("nvlink_domain") != requirements.required_nvlink_domain:
            return False
        return True

    @staticmethod
    def _topology_group_key(gpu: dict[str, Any]) -> str:
        payload = json.loads(gpu["payload_json"])
        topology_domain = payload.get("topology_domain")
        if topology_domain:
            return f"topology:{topology_domain}"
        return f'isolated:{gpu["resource_key"]}'

    @classmethod
    def _verified_gpu_nic_rdma_path(cls, row: dict[str, Any], gpu_uuid: str | None) -> tuple[dict[str, Any], ...]:
        if not gpu_uuid:
            return ()
        evidence = json.loads(row["evidence_json"])
        network = evidence.get("network")
        if not isinstance(network, dict):
            return ()
        locality = network.get("gpu_nic_locality")
        rdma = network.get("rdma")
        if not isinstance(locality, list) or not isinstance(rdma, dict):
            return ()
        links = rdma.get("links")
        if not isinstance(links, list):
            return ()
        devices = {
            str(item.get("device") or "").strip()
            for item in (rdma.get("devices") or [])
            if isinstance(item, dict) and str(item.get("device") or "").strip()
        }
        verified = []
        for item in locality:
            if not isinstance(item, dict) or str(item.get("gpu_uuid") or "").strip() != gpu_uuid:
                continue
            device = str(item.get("rdma_device") or "").strip()
            port = item.get("rdma_port")
            link_layer = str(item.get("link_layer") or "").strip()
            if not device or not isinstance(port, int) or port < 1 or not link_layer or device not in devices:
                continue
            matches = [
                link for link in links
                if isinstance(link, dict)
                and str(link.get("rdma_device") or "").strip() == device
                and link.get("port") == port
                and str(link.get("link_layer") or "").strip() == link_layer
                and str(link.get("state") or "").strip().upper() == "ACTIVE"
                and str(link.get("physical_state") or "").strip().upper() in {"LINK_UP", "LINK_ACTIVE"}
            ]
            quarantined = row.get("quarantined_fabric_paths") or ()
            blocked = any(
                isinstance(path, dict)
                and str(path.get("nic") or "").strip() == str(item.get("nic") or "").strip()
                and str(path.get("rdma_device") or "").strip() == device
                and path.get("rdma_port") == port
                and str(path.get("link_layer") or "").strip() == link_layer
                for path in quarantined
            )
            if matches and not blocked:
                link = dict(matches[0])
                verified.append({
                    **item,
                    "node_id": str(row.get("node_id") or "").strip(),
                    "rdma_device": device,
                    "rdma_port": port,
                    "link_layer": link_layer,
                    "verified_rdma_link": link,
                    "bandwidth_gbps": cls._path_bandwidth_gbps(link),
                    "latency_us": cls._path_latency_us(link),
                })
        return tuple(verified)

    @staticmethod
    def _path_bandwidth_gbps(path: dict[str, Any]) -> float | None:
        for key in ("bandwidth_gbps", "link_bandwidth_gbps", "throughput_gbps", "speed_gbps"):
            value = path.get(key)
            if value is None:
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return None

    @staticmethod
    def _path_latency_us(path: dict[str, Any]) -> float | None:
        for key in ("latency_us", "link_latency_us", "fabric_latency_us"):
            value = path.get(key)
            if value is None:
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return None

    @classmethod
    def _rank_fabric_paths(cls, paths: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        def key(path: dict[str, Any]) -> tuple:
            bandwidth = path.get("bandwidth_gbps")
            latency = path.get("latency_us")
            return (
                0 if bandwidth is not None else 1,
                -(float(bandwidth) if bandwidth is not None else 0.0),
                0 if latency is not None else 1,
                float(latency) if latency is not None else float("inf"),
                str(path.get("rdma_device") or ""),
                int(path.get("rdma_port") or 0),
            )
        return tuple(sorted((dict(path) for path in paths), key=key))

    @classmethod
    def _fabric_path_contract(
        cls,
        row: dict[str, Any],
        gpu_uuid: str | None,
        *,
        min_bandwidth_gbps: float | None = None,
        max_latency_us: float | None = None,
        require_redundant: bool = False,
    ) -> dict[str, Any] | None:
        paths = cls._rank_fabric_paths(cls._verified_gpu_nic_rdma_path(row, gpu_uuid))
        if min_bandwidth_gbps is not None:
            paths = tuple(path for path in paths if path.get("bandwidth_gbps") is not None and float(path["bandwidth_gbps"]) >= min_bandwidth_gbps)
        if max_latency_us is not None:
            paths = tuple(path for path in paths if path.get("latency_us") is not None and float(path["latency_us"]) <= max_latency_us)
        if not paths:
            return None
        independent = []
        seen = set()
        for path in paths:
            identity = (
                str(path.get("nic") or ""),
                str(path.get("rdma_device") or ""),
                int(path.get("rdma_port") or 0),
                str(path.get("link_layer") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            independent.append(path)
        if require_redundant and len(independent) < 2:
            return None
        primary = independent[0]
        return {
            "primary_path": primary,
            "redundant_paths": tuple(independent[1:]),
            "path_count": len(independent),
            "selection_policy": "highest_verified_bandwidth_then_lowest_verified_latency",
            "bandwidth_gbps": primary.get("bandwidth_gbps"),
            "latency_us": primary.get("latency_us"),
        }

    @staticmethod
    def _has_explicit_physical_path_evidence(row: dict[str, Any], gpu_uuid: str | None) -> bool:
        if not gpu_uuid:
            return False
        evidence = json.loads(row["evidence_json"])
        network = evidence.get("network")
        if not isinstance(network, dict):
            return False
        locality = network.get("gpu_nic_locality")
        rdma = network.get("rdma")
        return (
            isinstance(locality, list)
            and any(
                isinstance(item, dict) and str(item.get("gpu_uuid") or "").strip() == str(gpu_uuid).strip()
                for item in locality
            )
            and isinstance(rdma, dict)
            and isinstance(rdma.get("links"), list)
        )

    @classmethod
    def _gpu_placement_structure_key(
        cls,
        gpu: dict[str, Any],
        gpus: list[dict[str, Any]],
    ) -> tuple[int, float, float, int, int]:
        """Return only the verified physical/topology portion of GPU placement rank."""
        payload = json.loads(gpu["payload_json"])
        topology_key = cls._topology_group_key(gpu)
        topology_counts = sum(1 for candidate in gpus if cls._topology_group_key(candidate) == topology_key)
        numa_node = payload.get("numa_node")
        numa_counts = sum(
            1
            for candidate in gpus
            if cls._topology_group_key(candidate) == topology_key
            and json.loads(candidate["payload_json"]).get("numa_node") == numa_node
        )
        paths = cls._rank_fabric_paths(cls._verified_gpu_nic_rdma_path(gpu, payload.get("gpu_uuid")))
        primary = paths[0] if paths else {}
        bandwidth = primary.get("bandwidth_gbps")
        latency = primary.get("latency_us")
        return (
            0 if paths else 1,
            -(float(bandwidth) if bandwidth is not None else 0.0),
            float(latency) if latency is not None else float("inf"),
            -topology_counts,
            -numa_counts,
        )

    @classmethod
    def _rank_gpus_for_placement(cls, gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
        topology_counts: dict[str, int] = {}
        numa_counts: dict[tuple[str, Any], int] = {}
        for gpu in gpus:
            payload = json.loads(gpu["payload_json"])
            topology_key = cls._topology_group_key(gpu)
            topology_counts[topology_key] = topology_counts.get(topology_key, 0) + 1
            numa_key = (topology_key, payload.get("numa_node"))
            numa_counts[numa_key] = numa_counts.get(numa_key, 0) + 1

        def rank(gpu: dict[str, Any]) -> tuple[int, int, int, str, str]:
            payload = json.loads(gpu["payload_json"])
            topology_key = cls._topology_group_key(gpu)
            numa_key = (topology_key, payload.get("numa_node"))
            physical_path = bool(cls._verified_gpu_nic_rdma_path(gpu, payload.get("gpu_uuid")))
            paths = cls._rank_fabric_paths(cls._verified_gpu_nic_rdma_path(gpu, payload.get("gpu_uuid")))
            primary = paths[0] if paths else {}
            bandwidth = primary.get("bandwidth_gbps")
            latency = primary.get("latency_us")
            return (
                0 if physical_path else 1,
                -(float(bandwidth) if bandwidth is not None else 0.0),
                float(latency) if latency is not None else float("inf"),
                -topology_counts[topology_key],
                -numa_counts[numa_key],
                str(payload.get("gpu_id") or gpu.get("resource_key") or ""),
                str(payload.get("gpu_uuid") or ""),
            )

        return sorted(gpus, key=rank)

    @classmethod
    def _node_topology_score(cls, candidate: dict[str, Any]) -> tuple[int, int, int]:
        ranked = cls._rank_gpus_for_placement(candidate["gpus"])
        if not ranked:
            return (0, 0, 0)
        first = ranked[0]
        first_payload = json.loads(first["payload_json"])
        topology_key = cls._topology_group_key(first)
        same_topology = [gpu for gpu in candidate["gpus"] if cls._topology_group_key(gpu) == topology_key]
        numa_node = first_payload.get("numa_node")
        same_numa = [
            gpu for gpu in same_topology
            if json.loads(gpu["payload_json"]).get("numa_node") == numa_node
        ]
        return (len(same_topology), len(same_numa), len(candidate["gpus"]))

    @staticmethod
    def _node_from_rows(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        nodes: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            nodes.setdefault(str(row["node_id"]), []).append(row)
        return nodes

    @staticmethod
    def _verified_network_fabric_evidence(row: dict[str, Any]) -> dict[str, str] | None:
        evidence = json.loads(row["evidence_json"])
        network = evidence.get("network")
        if not isinstance(network, dict) or not network.get("source"):
            return None
        fabric_domains = network.get("fabric_domains")
        if not isinstance(fabric_domains, dict):
            return None
        value = fabric_domains.get(str(row["node_id"]))
        domain = str(value).strip() if value is not None and str(value).strip() else None
        if domain is None:
            return None
        return {"domain": domain, "source": str(network["source"]).strip()}

    @classmethod
    def _verified_network_domains(cls, candidate: dict[str, Any]) -> tuple[str, ...]:
        evidence = json.loads(candidate["cpu"]["evidence_json"])
        network = evidence.get("network")
        if not isinstance(network, dict) or not network.get("source"):
            return ()
        domains = network.get("network_domains")
        if isinstance(domains, dict):
            domains = domains.get(str(candidate["node_id"]))
        if isinstance(domains, str):
            domains = [domains]
        if not isinstance(domains, list):
            fabric = cls._verified_network_fabric_evidence(candidate["cpu"])
            return (fabric["domain"],) if fabric else ()
        return tuple(sorted({str(domain).strip() for domain in domains if str(domain).strip()}))

    @classmethod
    def _shared_verified_network_domain(cls, candidates: list[dict[str, Any]]) -> dict[str, str] | None:
        if len(candidates) < 2:
            return None
        domain_sets = [set(cls._verified_network_domains(candidate)) for candidate in candidates]
        if any(not domains for domains in domain_sets):
            return None
        shared = set.intersection(*domain_sets)
        if not shared:
            return None
        domain = sorted(shared)[0]
        sources = set()
        for candidate in candidates:
            evidence = json.loads(candidate["cpu"]["evidence_json"]).get("network") or {}
            source = str(evidence.get("source") or "").strip()
            if source:
                sources.add(source)
        if len(sources) != 1:
            return None
        return {"domain": domain, "source": next(iter(sources))}

    @staticmethod
    def _gpu_nic_locality_evidence(row: dict[str, Any], gpu_uuid: str | None) -> tuple[dict[str, Any], ...]:
        if not gpu_uuid:
            return ()
        evidence = json.loads(row["evidence_json"])
        network = evidence.get("network")
        if not isinstance(network, dict):
            return ()
        locality = network.get("gpu_nic_locality")
        if not isinstance(locality, list):
            return ()
        return tuple(
            item for item in locality
            if isinstance(item, dict) and str(item.get("gpu_uuid") or "").strip() == str(gpu_uuid).strip()
        )

    def _candidates(self, requirements: ComputeRequirements) -> list[dict[str, Any]]:
        rows = self.inventory.eligible()
        grouped = self._node_from_rows(rows)
        candidates = []
        performance_history = self._performance_history(requirements)
        route_health = self._route_health()
        for node_id, node_rows in grouped.items():
            if requirements.allowed_node_ids and node_id not in set(requirements.allowed_node_ids):
                continue
            cpu = next((r for r in node_rows if r["resource_type"] == "cpu"), None)
            gpus = [r for r in node_rows if r["resource_type"] == "gpu"]
            if cpu is None:
                continue
            node_payload = json.loads(cpu["payload_json"])
            cpu_resource = node_payload.get("cpu") or {}
            if int(cpu_resource.get("cpu_count", 0)) < requirements.min_cpu_count:
                continue
            if int(cpu_resource.get("memory_bytes", 0)) < requirements.min_memory_bytes:
                continue
            compatible = [gpu for gpu in gpus if self._gpu_matches(gpu, requirements.gpu)]
            if requirements.gpu.min_fabric_bandwidth_gbps is not None or requirements.gpu.max_fabric_latency_us is not None or requirements.gpu.require_redundant_fabric_path:
                compatible = [
                    gpu for gpu in compatible
                    if self._fabric_path_contract(
                        gpu,
                        json.loads(gpu["payload_json"]).get("gpu_uuid"),
                        min_bandwidth_gbps=requirements.gpu.min_fabric_bandwidth_gbps,
                        max_latency_us=requirements.gpu.max_fabric_latency_us,
                        require_redundant=requirements.gpu.require_redundant_fabric_path,
                    ) is not None
                ]
            if requirements.topology_domain is not None:
                compatible = [
                    gpu for gpu in compatible
                    if json.loads(gpu["payload_json"]).get("topology_domain") == requirements.topology_domain
                ]
            if requirements.gpu.require_nccl:
                nccl = node_payload.get("nccl_version")
                if not nccl:
                    continue
                if requirements.workload_class == WorkloadClass.MULTI_NODE_GPU:
                    compatible = [
                        gpu for gpu in compatible
                        if not self._has_explicit_physical_path_evidence(
                            gpu, json.loads(gpu["payload_json"]).get("gpu_uuid")
                        )
                        or bool(self._verified_gpu_nic_rdma_path(
                            gpu, json.loads(gpu["payload_json"]).get("gpu_uuid")
                        ))
                    ]
            # A multi-node request can combine GPUs from multiple nodes, so
            # each candidate only needs to contribute at least one compatible GPU.
            # Single-node workloads still require the full GPU count on one node.
            if requirements.workload_class == WorkloadClass.MULTI_NODE_GPU:
                if not compatible:
                    continue
            elif requirements.gpu.gpu_count > len(compatible):
                continue
            candidates.append({
                "node_id": node_id,
                "cpu": cpu,
                "gpus": sorted(
                    self._rank_gpus_for_placement(compatible),
                    key=lambda gpu: (
                        self._gpu_placement_structure_key(gpu, compatible),
                        self._gpu_performance_key(gpu, performance_history, requirements),
                        self._gpu_route_health_key(gpu, route_health),
                        str(gpu.get("resource_key") or ""),
                    ),
                ),
                "payload": node_payload,
            })
        return candidates

    def allocate(self, requirements: ComputeRequirements, allocation_id: str) -> ComputeAllocation:
        if not allocation_id.strip():
            raise ValueError("allocation_id is required")
        placement = None
        if requirements.gpu.gpu_count > 0:
            placement = self.placement(requirements)
        candidates = self._candidates(requirements)
        if placement is not None:
            selected_keys = set(placement.selected_resource_keys)
            selected_nodes = set(placement.selected_node_ids)
            candidates = [
                {
                    **candidate,
                    "gpus": [
                        gpu for gpu in candidate["gpus"]
                        if str(gpu["resource_key"]) in selected_keys
                    ],
                }
                for candidate in candidates
                if str(candidate["node_id"]) in selected_nodes
            ]
        performance_history = self._performance_history(requirements)
        route_health = self._route_health()
        needed = requirements.gpu.gpu_count
        if requirements.workload_class == WorkloadClass.IO_BOUND and needed == 0:
            needed = 0

        selected: list[dict[str, Any]] = []
        if requirements.workload_class == WorkloadClass.MULTI_NODE_GPU:
            # A distributed allocation is one execution domain. Never mix
            # providers or domains inside a single physical allocation.
            groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for candidate in candidates:
                key = (str(candidate["cpu"]["provider_id"]), str(candidate["cpu"]["domain_id"]))
                groups.setdefault(key, []).append(candidate)
            ranked_groups = sorted(
                groups.items(),
                key=lambda item: (
                    tuple(sum(self._node_topology_score(candidate)[index] for candidate in item[1]) for index in range(3)),
                    tuple(sorted((candidate["node_id"] for candidate in item[1]), reverse=True)),
                ),
                reverse=True,
            )
            for (_provider_id, _domain_id), group in ranked_groups:
                network_groups: dict[str, list[dict[str, Any]]] = {}
                for candidate in group:
                    for network_domain in self._verified_network_domains(candidate):
                        network_groups.setdefault(network_domain, []).append(candidate)
                network_group_options = [
                    (fabric, members)
                    for fabric, members in network_groups.items()
                    if len(members) >= 2
                ]
                if network_group_options:
                    network_group_options.sort(
                        key=lambda item: (
                            -sum(len(candidate["gpus"]) for candidate in item[1]),
                            -sum(self._node_topology_score(candidate)[0] for candidate in item[1]),
                            tuple(sorted(candidate["node_id"] for candidate in item[1])),
                        )
                    )
                    candidate_pool = network_group_options[0][1]
                else:
                    candidate_pool = group
                group_selected: list[dict[str, Any]] = []
                total = 0
                ranked_group = sorted(
                    candidate_pool,
                    key=lambda candidate: (
                        -self._node_topology_score(candidate)[0],
                        -self._node_topology_score(candidate)[1],
                        -self._node_topology_score(candidate)[2],
                        self._gpu_performance_key(candidate["gpus"][0], performance_history, requirements) if candidate["gpus"] else (1, float("inf"), 0),
                        self._gpu_route_health_key(candidate["gpus"][0], route_health) if candidate["gpus"] else (1, float("inf"), float("inf"), float("inf"), 0),
                        str(candidate["node_id"]),
                    ),
                )
                for candidate in ranked_group:
                    if not candidate["gpus"]:
                        continue
                    group_selected.append(candidate)
                    total += len(candidate["gpus"])
                    if len(group_selected) >= 2 and total >= needed:
                        break
                if len(group_selected) >= 2 and total >= needed:
                    selected = group_selected
                    break
            if len(selected) < 2 or sum(len(c["gpus"]) for c in selected) < needed:
                raise ComputeSchedulingError("no compatible multi-node allocation within one provider and domain")
        else:
            ranked_candidates = sorted(
                candidates,
                key=lambda candidate: (
                    -self._node_topology_score(candidate)[0],
                    -self._node_topology_score(candidate)[1],
                    -self._node_topology_score(candidate)[2],
                    self._gpu_performance_key(candidate["gpus"][0], performance_history, requirements) if candidate["gpus"] else (1, float("inf"), 0),
                    self._gpu_route_health_key(candidate["gpus"][0], route_health) if candidate["gpus"] else (1, float("inf"), float("inf"), float("inf"), 0),
                    str(candidate["node_id"]),
                ),
            )
            for candidate in ranked_candidates:
                if len(candidate["gpus"]) >= needed:
                    selected = [candidate]
                    break
            if not selected:
                raise ComputeSchedulingError("no compatible allocation")

        selected_network = self._shared_verified_network_domain(selected)
        resources = [candidate["cpu"] for candidate in selected]
        gpu_rows: list[dict[str, Any]] = []
        remaining = needed
        if requirements.workload_class == WorkloadClass.MULTI_NODE_GPU:
            # Every selected node contributes one GPU first. Remaining GPUs are
            # then packed deterministically without ever removing a node.
            if needed < len(selected):
                raise ComputeSchedulingError("multi-node allocation needs at least one GPU per selected node")
            for candidate in selected:
                ranked = candidate["gpus"]
                gpu_rows.append(ranked[0])
                remaining -= 1
            for candidate in selected:
                if remaining <= 0:
                    break
                ranked = candidate["gpus"]
                extras = ranked[1:1 + remaining]
                gpu_rows.extend(extras)
                remaining -= len(extras)
        else:
            for candidate in selected:
                take = min(remaining, len(candidate["gpus"]))
                gpu_rows.extend(candidate["gpus"][:take])
                remaining -= take
        if remaining != 0:
            raise ComputeSchedulingError("selected allocation cannot satisfy the exact GPU count")
        resources.extend(gpu_rows)

        keys = [row["resource_key"] for row in resources]
        try:
            self.inventory.reserve_allocation(allocation_id, next(iter({row["provider_id"] for row in resources})),
                                             next(iter({row["domain_id"] for row in resources})), keys)
        except ValueError as error:
            raise ComputeSchedulingError(str(error)) from error

        provider_ids = {row["provider_id"] for row in resources}
        domain_ids = {row["domain_id"] for row in resources}
        if len(provider_ids) != 1 or len(domain_ids) != 1:
            self.release(keys)
            raise ComputeSchedulingError("allocation must remain within one provider and domain")
        if placement is not None:
            try:
                self.inventory.persist_placement(placement)
            except (TypeError, ValueError, sqlite3.Error) as error:
                self.release(keys)
                raise ComputeSchedulingError(f"placement persistence failed: {error}") from error
        return ComputeAllocation(
            allocation_id=allocation_id,
            provider_id=next(iter(provider_ids)),
            domain_id=next(iter(domain_ids)),
            node_ids=tuple(dict.fromkeys(row["node_id"] for row in resources)),
            resource_ids=tuple(
                f'{row["node_id"]}/{row["gpu_id"]}' if row["resource_type"] == "gpu"
                else f'{row["node_id"]}/cpu'
                for row in resources
            ),
            resource_keys=tuple(keys),
            placement_id=placement.placement_id if placement is not None else None,
            capability_evidence=tuple(
                json.loads(row["payload_json"]) | {"resource_key": row["resource_key"]} | (
                    {
                        "placement_id": placement.placement_id,
                        "placement_schema_version": 1,
                    }
                    if placement is not None
                    else {}
                ) | (
                    {"placement_decision": {
                        "signal": (
                            "verified_gpu_nic_rdma_path"
                            if self._verified_gpu_nic_rdma_path(
                                row, json.loads(row["payload_json"]).get("gpu_uuid")
                            )
                            else "verified_topology_domain"
                            if json.loads(row["payload_json"]).get("topology_domain")
                            else "verified_network_domain"
                            if selected_network
                            else "verified_gpu_nic_locality"
                        ),
                        "topology_domain": json.loads(row["payload_json"]).get("topology_domain"),
                        "topology_source": json.loads(row["payload_json"]).get("topology_source") or (
                            json.loads(row["evidence_json"]).get("topology") or {}
                        ).get("source"),
                        "numa_node": json.loads(row["payload_json"]).get("numa_node"),
                        "numa_source": json.loads(row["payload_json"]).get("topology_source") or (
                            json.loads(row["evidence_json"]).get("topology") or {}
                        ).get("source"),
                        **({
                            "network_fabric_domain": network_evidence["domain"],
                            "network_source": network_evidence["source"],
                        } if (network_evidence := self._verified_network_fabric_evidence(row)) else {}),
                        **({
                            "network_domain": selected_network["domain"],
                            "network_source": selected_network["source"],
                        } if selected_network else {}),
                        **({
                            "gpu_nic_locality": self._gpu_nic_locality_evidence(
                                row, json.loads(row["payload_json"]).get("gpu_uuid")
                            ),
                        } if self._gpu_nic_locality_evidence(
                            row, json.loads(row["payload_json"]).get("gpu_uuid")
                        ) else {}),
                        **({
                            "verified_gpu_nic_rdma_path": list(self._verified_gpu_nic_rdma_path(
                                row, json.loads(row["payload_json"]).get("gpu_uuid")
                            )),
                        } if self._verified_gpu_nic_rdma_path(
                            row, json.loads(row["payload_json"]).get("gpu_uuid")
                        ) else {}),
                        **({
                            "fabric_path_contract": self._fabric_path_contract(
                                row,
                                json.loads(row["payload_json"]).get("gpu_uuid"),
                                min_bandwidth_gbps=requirements.gpu.min_fabric_bandwidth_gbps,
                                max_latency_us=requirements.gpu.max_fabric_latency_us,
                                require_redundant=requirements.gpu.require_redundant_fabric_path,
                            ),
                        } if row["resource_type"] == "gpu" and self._fabric_path_contract(
                            row,
                            json.loads(row["payload_json"]).get("gpu_uuid"),
                            min_bandwidth_gbps=requirements.gpu.min_fabric_bandwidth_gbps,
                            max_latency_us=requirements.gpu.max_fabric_latency_us,
                            require_redundant=requirements.gpu.require_redundant_fabric_path,
                        ) else {}),
                    }}
                    if row["resource_type"] == "gpu" and (
                        json.loads(row["payload_json"]).get("topology_domain")
                        or self._verified_network_fabric_evidence(row)
                        or selected_network
                        or self._gpu_nic_locality_evidence(row, json.loads(row["payload_json"]).get("gpu_uuid"))
                    )
                    else {}
                )
                for row in resources
            ),
        )

    def release(self, resource_keys: Iterable[str]) -> int:
        keys = tuple(dict.fromkeys(resource_keys))
        if not keys:
            return 0
        target = set(keys)
        for allocation in self.inventory.allocations():
            if allocation["state"] in {"reserved", "bound"} and set(allocation["resource_keys"]) == target:
                return self.inventory.release_allocation(
                    allocation["allocation_id"],
                    task_id=allocation["task_id"],
                    attempt_id=allocation["attempt_id"],
                    generation=allocation["generation"],
                    reason="scheduler release",
                )
        placeholders = ",".join("?" for _ in keys)
        with self.inventory._connect() as connection:
            cursor = connection.execute(
                f"UPDATE compute_resource_inventory SET state=? WHERE resource_key IN ({placeholders}) AND state=?",
                (ResourceState.AVAILABLE.value, *keys, ResourceState.RESERVED.value),
            )
            connection.commit()
            return cursor.rowcount
