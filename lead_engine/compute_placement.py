"""Complete, evidence-first GPU placement construction.

This module contains placement vocabulary and deterministic candidate evaluation.
It deliberately does not reserve inventory or start execution.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .compute_fabric_telemetry import physical_path_key


@dataclass(frozen=True)
class PlacementDecision:
    placement_id: str
    provider_id: str
    domain_id: str
    workload_signature: tuple[tuple[str, Any], ...]
    selected_gpu_ids: tuple[str, ...]
    selected_node_ids: tuple[str, ...]
    selected_resource_keys: tuple[str, ...]
    evidence: dict[str, Any]
    decision_trace: tuple[dict[str, Any], ...]


class PlacementEvaluator:
    """Construct complete placements from already observed inventory facts."""

    def __init__(
        self,
        scheduler: Any,
        requirements: Any,
        rows: list[dict[str, Any]],
        performance_history: dict[str, dict[str, Any]],
        route_health: dict[str, dict[str, Any]],
        physical_paths: Iterable[dict[str, Any]] = (),
    ):
        self.scheduler = scheduler
        self.requirements = requirements
        self.rows = rows
        self.performance_history = performance_history
        self.route_health = route_health
        self.physical_paths = tuple(physical_paths)
        self.trace: list[dict[str, Any]] = []

    def _trace(self, stage: str, status: str, **details: Any) -> None:
        self.trace.append({
            "stage": stage,
            "status": status,
            **details,
        })

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        return json.loads(row["payload_json"])

    def _compatible_gpu_rows(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        compatible = [
            row for row in rows
            if row["resource_type"] == "gpu"
            and self.scheduler._gpu_matches(row, self.requirements.gpu)
        ]
        if self.requirements.topology_domain is not None:
            compatible = [
                row for row in compatible
                if self._payload(row).get("topology_domain") == self.requirements.topology_domain
            ]
        return compatible

    def _node_rows(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self.rows:
            grouped.setdefault(str(row["node_id"]), []).append(row)
        return grouped

    def _node_candidate(self, node_id: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        cpu = next((row for row in rows if row["resource_type"] == "cpu"), None)
        if cpu is None:
            return None
        payload = self._payload(cpu)
        cpu_resource = payload.get("cpu") or {}
        if int(cpu_resource.get("cpu_count", 0)) < self.requirements.min_cpu_count:
            return None
        if int(cpu_resource.get("memory_bytes", 0)) < self.requirements.min_memory_bytes:
            return None
        gpus = self._compatible_gpu_rows(rows)
        if self.requirements.allowed_node_ids and node_id not in set(self.requirements.allowed_node_ids):
            return None
        return {
            "node_id": node_id,
            "cpu": cpu,
            "gpus": gpus,
            "payload": payload,
        }

    def _verified_paths(self, gpu: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        payload = self._payload(gpu)
        return self.scheduler._verified_gpu_nic_rdma_path(gpu, payload.get("gpu_uuid"))

    def _network_domains(self, candidate: dict[str, Any]) -> tuple[str, ...]:
        return self.scheduler._verified_network_domains(candidate)

    def _valid_gpu(self, gpu: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        payload = self._payload(gpu)
        paths = self._verified_paths(gpu)
        evidence = {
            "gpu_uuid": payload.get("gpu_uuid"),
            "gpu_id": payload.get("gpu_id"),
            "node_id": gpu["node_id"],
            "paths": list(paths),
        }
        fabric_requested = (
            self.requirements.gpu.min_fabric_bandwidth_gbps is not None
            or self.requirements.gpu.max_fabric_latency_us is not None
            or self.requirements.gpu.require_redundant_fabric_path
        )
        if fabric_requested and self.scheduler._fabric_path_contract(
            gpu,
            payload.get("gpu_uuid"),
            min_bandwidth_gbps=self.requirements.gpu.min_fabric_bandwidth_gbps,
            max_latency_us=self.requirements.gpu.max_fabric_latency_us,
            require_redundant=self.requirements.gpu.require_redundant_fabric_path,
        ) is None:
            return False, "missing_required_verified_fabric_path", evidence
        return True, "verified", evidence

    def _valid_candidate(self, candidate: tuple[dict[str, Any], ...]) -> tuple[bool, dict[str, Any]]:
        gpu_evidence = []
        for gpu in candidate:
            valid, reason, evidence = self._valid_gpu(gpu)
            gpu_evidence.append(evidence | {"valid": valid, "reason": reason})
            if not valid:
                return False, {
                    "stage": "complete_communication_path_validity",
                    "reason": reason,
                    "gpu": evidence,
                    "gpu_evidence": gpu_evidence,
                }

        concrete_ok, concrete_paths, concrete_reason = self._concrete_path_evidence(candidate)
        if not concrete_ok:
            return False, {
                "stage": "complete_communication_path_validity",
                "reason": concrete_reason,
                "physical_paths": concrete_paths,
            }

        node_ids = tuple(dict.fromkeys(str(gpu["node_id"]) for gpu in candidate))
        node_candidates = [
            self._node_candidate(node_id, self._node_rows()[node_id])
            for node_id in node_ids
        ]
        node_candidates = [item for item in node_candidates if item is not None]
        if len(node_candidates) != len(node_ids):
            return False, {
                "stage": "resource_eligibility",
                "reason": "selected_node_is_not_eligible",
                "node_ids": node_ids,
            }

        shared_network = None
        if len(node_ids) > 1:
            shared_network = self.scheduler._shared_verified_network_domain(node_candidates)
            network_known = any(self._network_domains(candidate) for candidate in node_candidates)
            if network_known and shared_network is None:
                return False, {
                    "stage": "complete_communication_path_validity",
                    "reason": "missing_verified_shared_network_domain",
                    "node_ids": node_ids,
                }

        topology = [
            {
                "gpu_id": self._payload(gpu).get("gpu_id"),
                "gpu_uuid": self._payload(gpu).get("gpu_uuid"),
                "node_id": gpu["node_id"],
                "topology_domain": self._payload(gpu).get("topology_domain"),
                "numa_node": self._payload(gpu).get("numa_node"),
                "topology_source": self._payload(gpu).get("topology_source"),
            }
            for gpu in candidate
        ]
        return True, {
            "gpu_evidence": gpu_evidence,
            "node_ids": node_ids,
            "shared_network": shared_network,
            "topology": topology,
            "concrete_physical_paths": concrete_paths,
        }

    def _concrete_path_evidence(self, candidate: tuple[dict[str, Any], ...]) -> tuple[bool, list[dict[str, Any]], str]:
        selected = {str(self._payload(gpu).get("gpu_uuid") or "") for gpu in candidate}
        selected.discard("")
        if len({str(gpu["node_id"]) for gpu in candidate}) < 2:
            return True, [], "same_node"
        if not self.physical_paths:
            return True, [], "no_canonical_concrete_path_records"
        paths = [
            path for path in self.physical_paths
            if str(path.get("state") or "") in {"VERIFIED", "MEASURED", "REVERIFIED"}
        ]
        evidence = [
            path for path in paths
            if str(path.get("source_gpu") or "").removeprefix("gpu:") in selected
            or str(path.get("destination_gpu") or "").removeprefix("gpu:") in selected
        ]
        node_pairs = {
            tuple(sorted((str(gpu["node_id"]), str(other["node_id"]))))
            for index, gpu in enumerate(candidate)
            for other in candidate[index + 1:]
            if str(gpu["node_id"]) != str(other["node_id"])
        }
        covered_pairs = set()
        for path in evidence:
            source = str(path.get("source_gpu") or "").removeprefix("gpu:")
            destination = str(path.get("destination_gpu") or "").removeprefix("gpu:")
            for gpu in selected:
                if gpu == source or gpu == destination:
                    continue
            source_node = next((str(gpu["node_id"]) for gpu in candidate if str(self._payload(gpu).get("gpu_uuid")) == source), None)
            destination_node = next((str(gpu["node_id"]) for gpu in candidate if str(self._payload(gpu).get("gpu_uuid")) == destination), None)
            if source_node and destination_node and source_node != destination_node:
                covered_pairs.add(tuple(sorted((source_node, destination_node))))
        missing = node_pairs - covered_pairs
        return not missing, evidence, "missing_verified_concrete_inter_node_path" if missing else "verified"

    def _candidate_performance(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        observations = []
        for gpu in candidate:
            payload = self._payload(gpu)
            paths = self._verified_paths(gpu)
            for path in paths:
                identity = {
                    key: path[key]
                    for key in (
                        "node_id", "gpu_uuid", "nic", "nic_pci_bus_id",
                        "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer",
                    )
                    if path.get(key) is not None and str(path.get(key)).strip()
                }
                if not identity:
                    continue
                legacy_key = physical_path_key(identity)
                workload = {
                    "workload_class": getattr(
                        getattr(self.requirements, "workload_class", None),
                        "value",
                        getattr(self.requirements, "workload_class", None),
                    ),
                    **dict(getattr(self.requirements, "performance_signature", ()) or ()),
                }
                from .compute_fabric_telemetry import workload_performance_key
                key = workload_performance_key(identity, workload)
                observation = self.performance_history.get(key)
                if observation is None:
                    observation = self.performance_history.get(legacy_key)
                if observation is not None:
                    observations.append(observation)
        if not observations:
            return (1, float("inf"), 0)
        elapsed = [float(item.get("avg_all_reduce_elapsed_ms", float("inf"))) for item in observations]
        return (0, sum(elapsed) / len(elapsed), -sum(int(item.get("sample_count", 0)) for item in observations))

    def _candidate_route_health(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        observations = []
        for gpu in candidate:
            for path in self._verified_paths(gpu):
                try:
                    key = physical_path_key(path)
                except ValueError:
                    continue
                if key in self.route_health:
                    observations.append(self.route_health[key])
        if not observations:
            return (1, float("inf"), float("inf"), float("inf"), 0)
        return min(
            (
                0,
                float(item.get("latency_delta_from_mean_ms", float("inf"))),
                float(item.get("failure_rate", float("inf"))),
                float(item.get("latest_latency_ms", float("inf"))),
                -int(item.get("sample_count", 0)),
            )
            for item in observations
        )

    def _stable_key(self, candidate: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        return tuple(sorted(str(row["resource_key"]) for row in candidate))

    def _rank_gpu_rows(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates = list(rows)
        return sorted(
            candidates,
            key=lambda gpu: (
                self.scheduler._gpu_placement_structure_key(gpu, candidates),
                self.scheduler._gpu_performance_key(gpu, self.performance_history, self.requirements),
                self.scheduler._gpu_route_health_key(gpu, self.route_health),
                str(gpu.get("resource_key") or ""),
            ),
        )

    def _candidate_sets(self, nodes: list[dict[str, Any]]) -> Iterable[tuple[dict[str, Any], ...]]:
        needed = int(self.requirements.gpu.gpu_count)
        if needed < 1:
            return ()

        valid_nodes: list[dict[str, Any]] = []
        for node in nodes:
            valid_gpus = []
            for gpu in node["gpus"]:
                valid, reason, evidence = self._valid_gpu(gpu)
                if valid:
                    valid_gpus.append(gpu)
                else:
                    self._trace(
                        "complete_communication_path_validity",
                        "rejected",
                        reason=reason,
                        resource_keys=(str(gpu["resource_key"]),),
                        evidence=evidence,
                    )
            ranked = self._rank_gpu_rows(valid_gpus)
            if ranked:
                valid_nodes.append({**node, "gpus": ranked})

        if self.requirements.workload_class.value != "multi_node_gpu":
            for node in valid_nodes:
                if len(node["gpus"]) >= needed:
                    yield tuple(node["gpus"][:needed])
            return

        if len(valid_nodes) < 2:
            return

        provider_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for node in valid_nodes:
            key = (str(node["cpu"]["provider_id"]), str(node["cpu"]["domain_id"]))
            provider_groups.setdefault(key, []).append(node)

        viable_groups = [
            group for group in provider_groups.values()
            if len(group) >= 2 and sum(len(node["gpus"]) for node in group) >= needed
        ]
        if not viable_groups:
            self._trace(
                "resource_eligibility",
                "rejected",
                reason="no_provider_and_domain_can_satisfy_complete_placement",
            )
            raise RuntimeError("no provider and domain can satisfy complete placement")

        # Prefer a verified shared network domain whenever network-domain
        # evidence is actually available. This prevents a high-capacity node
        # from being combined with an incompatible network island.
        network_group_options: list[tuple[str, list[dict[str, Any]]]] = []
        for group in viable_groups:
            domains: dict[str, list[dict[str, Any]]] = {}
            for node in group:
                for domain in self._network_domains(node):
                    domains.setdefault(domain, []).append(node)
            for domain, members in domains.items():
                if len(members) >= 2 and sum(len(node["gpus"]) for node in members) >= needed:
                    network_group_options.append((domain, members))
        if network_group_options:
            network_group_options.sort(
                key=lambda item: (
                    -sum(len(node["gpus"]) for node in item[1]),
                    -sum(self.scheduler._node_topology_score(node)[0] for node in item[1]),
                    str(item[0]),
                )
            )
            ranked_group = network_group_options[0][1]
        else:
            ranked_group = max(
                viable_groups,
                key=lambda group: (
                    sum(len(node["gpus"]) for node in group),
                    tuple(sorted(str(node["node_id"]) for node in group)),
                ),
            )

        # Build complete distributed candidates hierarchically rather than
        # enumerating the combinatorial GPU-set space. Each node contributes
        # verified GPUs, and nodes are ordered by their strongest verified
        # participant. The candidate is filled until the exact world size is
        # satisfied, with at least two nodes required.
        ranked_nodes = sorted(
            ranked_group,
            key=lambda node: (
                tuple(-value for value in self.scheduler._node_topology_score(node)),
                self.scheduler._gpu_performance_key(node["gpus"][0], self.performance_history, self.requirements),
                self.scheduler._gpu_route_health_key(node["gpus"][0], self.route_health),
                str(node["node_id"]),
            ),
        )
        selected_nodes = []
        total = 0
        for node in ranked_nodes:
            selected_nodes.append(node)
            total += len(node["gpus"])
            if len(selected_nodes) >= 2 and total >= needed:
                break
        if len(selected_nodes) < 2 or total < needed:
            return

        selected: list[dict[str, Any]] = []
        remaining = needed
        for node in selected_nodes:
            take = min(remaining, len(node["gpus"]))
            selected.extend(node["gpus"][:take])
            remaining -= take
            if remaining == 0:
                break
        if remaining == 0:
            yield tuple(selected)

    def evaluate(self) -> PlacementDecision:
        nodes = []
        grouped = self._node_rows()
        for node_id in sorted(grouped):
            node = self._node_candidate(node_id, grouped[node_id])
            if node is None:
                self._trace("resource_eligibility", "rejected", node_id=node_id, reason="node_not_eligible")
                continue
            if not node["gpus"]:
                self._trace("capability_compatibility", "rejected", node_id=node_id, reason="no_compatible_gpu")
                continue
            nodes.append(node)
        if not nodes:
            raise RuntimeError("no eligible GPU placement candidates")

        valid: list[tuple[tuple[dict[str, Any], ...], dict[str, Any]]] = []
        candidate_evidence: list[dict[str, Any]] = []
        rejection_count = 0
        for candidate in self._candidate_sets(nodes):
            valid_candidate, evidence = self._valid_candidate(candidate)
            if not valid_candidate:
                rejection_count += 1
                rejection = {
                    "status": "rejected",
                    "resource_keys": self._stable_key(candidate),
                    "stage": evidence["stage"],
                    "reason": evidence["reason"],
                    "evidence": evidence,
                }
                candidate_evidence.append(rejection)
                self._trace(
                    evidence["stage"],
                    "rejected",
                    reason=evidence["reason"],
                    resource_keys=self._stable_key(candidate),
                )
                continue
            accepted = {
                "status": "accepted",
                "resource_keys": self._stable_key(candidate),
                "evidence": evidence,
            }
            candidate_evidence.append(accepted)
            valid.append((candidate, evidence))
            self._trace(
                "complete_physical_validation",
                "accepted",
                resource_keys=self._stable_key(candidate),
            )

        if not valid:
            self._trace(
                "complete_physical_validation",
                "rejected",
                reason="no_complete_physical_placement",
                rejected_candidates=rejection_count,
            )
            raise RuntimeError("no complete physical placement")

        ranked = sorted(
            valid,
            key=lambda item: (
                self._candidate_performance(item[0]),
                self._candidate_route_health(item[0]),
                self._stable_key(item[0]),
            ),
        )
        selected, evidence = ranked[0]
        self._trace("workload_performance", "applied", key=self._candidate_performance(selected))
        self._trace("route_health", "applied", key=self._candidate_route_health(selected))
        self._trace("stable_resource_ordering", "applied", resource_keys=self._stable_key(selected))

        provider_ids = {str(row["provider_id"]) for row in selected}
        domain_ids = {str(row["domain_id"]) for row in selected}
        if len(provider_ids) != 1 or len(domain_ids) != 1:
            raise RuntimeError("complete placement must remain within one provider and domain")

        gpu_ids = tuple(sorted(f'{row["node_id"]}/{self._payload(row).get("gpu_id")}' for row in selected))
        node_ids = tuple(sorted({str(row["node_id"]) for row in selected}))
        resource_keys = tuple(sorted(str(row["resource_key"]) for row in selected))
        path_evidence = []
        locality = []
        for row in selected:
            payload = self._payload(row)
            path_evidence.extend(self._verified_paths(row))
            locality.extend(self.scheduler._gpu_nic_locality_evidence(row, payload.get("gpu_uuid")))

        workload_signature = tuple(getattr(self.requirements, "performance_signature", ()) or ())
        stable_identity = {
            "provider_id": next(iter(provider_ids)),
            "domain_id": next(iter(domain_ids)),
            "workload_class": getattr(
                getattr(self.requirements, "workload_class", None),
                "value",
                getattr(self.requirements, "workload_class", None),
            ),
            "workload_signature": workload_signature,
            "gpu_requirements": {
                "gpu_count": self.requirements.gpu.gpu_count,
                "min_vram_bytes": self.requirements.gpu.min_vram_bytes,
                "min_compute_capability": self.requirements.gpu.min_compute_capability,
                "required_cuda_version": self.requirements.gpu.required_cuda_version,
                "required_driver_version": self.requirements.gpu.required_driver_version,
                "required_nvlink_domain": self.requirements.gpu.required_nvlink_domain,
                "require_nccl": self.requirements.gpu.require_nccl,
                "min_fabric_bandwidth_gbps": self.requirements.gpu.min_fabric_bandwidth_gbps,
                "max_fabric_latency_us": self.requirements.gpu.max_fabric_latency_us,
                "require_redundant_fabric_path": self.requirements.gpu.require_redundant_fabric_path,
            },
            "min_cpu_count": self.requirements.min_cpu_count,
            "min_memory_bytes": self.requirements.min_memory_bytes,
            "same_node": self.requirements.same_node,
            "topology_domain": self.requirements.topology_domain,
            "allowed_node_ids": tuple(self.requirements.allowed_node_ids),
            "gpu_ids": gpu_ids,
            "node_ids": node_ids,
            "resource_keys": resource_keys,
            "paths": [
                {key: path.get(key) for key in sorted(path) if key not in {"verified_rdma_link", "bandwidth_gbps", "latency_us"}}
                for path in path_evidence
            ],
        }
        placement_id = hashlib.sha256(
            json.dumps(stable_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return PlacementDecision(
            placement_id=placement_id,
            provider_id=next(iter(provider_ids)),
            domain_id=next(iter(domain_ids)),
            workload_signature=workload_signature,
            selected_gpu_ids=gpu_ids,
            selected_node_ids=node_ids,
            selected_resource_keys=resource_keys,
            evidence={
                "physical_paths": path_evidence,
                "gpu_nic_rdma": locality,
                "topology": evidence["topology"],
                "shared_network": evidence["shared_network"],
                "concrete_physical_paths": evidence.get("concrete_physical_paths", []),
                "workload_performance": self._candidate_performance(selected),
                "route_health": self._candidate_route_health(selected),
                "candidate_evaluations": candidate_evidence,
                "rejection_count": rejection_count,
            },
            decision_trace=tuple(self.trace),
        )
