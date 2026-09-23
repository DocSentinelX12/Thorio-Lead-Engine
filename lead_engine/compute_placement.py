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
    ):
        self.scheduler = scheduler
        self.requirements = requirements
        self.rows = rows
        self.performance_history = performance_history
        self.route_health = route_health
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
        if self.requirements.gpu.require_nccl and not paths:
            return False, "missing_verified_gpu_nic_rdma_path", evidence
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
            if shared_network is None:
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
        }

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

    def _candidate_sets(self, nodes: list[dict[str, Any]]) -> Iterable[tuple[dict[str, Any], ...]]:
        needed = int(self.requirements.gpu.gpu_count)
        if needed < 1:
            return ()
        if self.requirements.workload_class.value == "multi_node_gpu":
            for node_count in range(2, len(nodes) + 1):
                for selected_nodes in itertools.combinations(nodes, node_count):
                    gpu_options = [tuple(node["gpus"]) for node in selected_nodes]
                    if any(not options for options in gpu_options):
                        continue
                    for selected in itertools.product(*gpu_options):
                        if len(selected) == needed:
                            yield selected
            return
        for node in nodes:
            if len(node["gpus"]) < needed:
                continue
            for selected in itertools.combinations(node["gpus"], needed):
                yield selected

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
        rejection_count = 0
        for candidate in self._candidate_sets(nodes):
            valid_candidate, evidence = self._valid_candidate(candidate)
            if not valid_candidate:
                rejection_count += 1
                self._trace(
                    evidence["stage"],
                    "rejected",
                    reason=evidence["reason"],
                    resource_keys=self._stable_key(candidate),
                )
                continue
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
                "workload_performance": self._candidate_performance(selected),
                "route_health": self._candidate_route_health(selected),
            },
            decision_trace=tuple(self.trace),
        )
