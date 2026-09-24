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
from .physical_fabric import AdaptiveFabricRouteSelector


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

    def __init__(self, scheduler: Any, requirements: Any, rows: list[dict[str, Any]], performance_history: dict[str, dict[str, Any]], route_health: dict[str, dict[str, Any]], physical_paths: Iterable[dict[str, Any]] = ()):
        self.scheduler = scheduler
        self.requirements = requirements
        self.rows = rows
        self.performance_history = performance_history
        self.route_health = route_health
        self.physical_paths = tuple(physical_paths)
        self.trace: list[dict[str, Any]] = []

    def _trace(self, stage: str, status: str, **details: Any) -> None:
        self.trace.append({"stage": stage, "status": status, **details})

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        return json.loads(row["payload_json"])

    def _compatible_gpu_rows(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        compatible = [row for row in rows if row["resource_type"] == "gpu" and self.scheduler._gpu_matches(row, self.requirements.gpu)]
        if self.requirements.topology_domain is not None:
            compatible = [row for row in compatible if self._payload(row).get("topology_domain") == self.requirements.topology_domain]
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
        if int(cpu_resource.get("cpu_count", 0)) < self.requirements.min_cpu_count or int(cpu_resource.get("memory_bytes", 0)) < self.requirements.min_memory_bytes:
            return None
        gpus = self._compatible_gpu_rows(rows)
        if self.requirements.allowed_node_ids and node_id not in set(self.requirements.allowed_node_ids):
            return None
        return {"node_id": node_id, "cpu": cpu, "gpus": gpus, "payload": payload}

    def _verified_paths(self, gpu: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        payload = self._payload(gpu)
        return self.scheduler._verified_gpu_nic_rdma_path(gpu, payload.get("gpu_uuid"))

    def _network_domains(self, candidate: dict[str, Any]) -> tuple[str, ...]:
        return self.scheduler._verified_network_domains(candidate)

    def _valid_gpu(self, gpu: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        payload = self._payload(gpu)
        paths = self._verified_paths(gpu)
        evidence = {"gpu_uuid": payload.get("gpu_uuid"), "gpu_id": payload.get("gpu_id"), "node_id": gpu["node_id"], "paths": list(paths)}
        canonical_paths_present = bool(self.physical_paths)
        legacy_fabric_requested = (
            self.requirements.gpu.require_redundant_fabric_path
            or (not canonical_paths_present and (
                self.requirements.gpu.min_fabric_bandwidth_gbps is not None
                or self.requirements.gpu.max_fabric_latency_us is not None
            ))
        )
        if legacy_fabric_requested and self.scheduler._fabric_path_contract(
            gpu,
            payload.get("gpu_uuid"),
            min_bandwidth_gbps=None if canonical_paths_present else self.requirements.gpu.min_fabric_bandwidth_gbps,
            max_latency_us=None if canonical_paths_present else self.requirements.gpu.max_fabric_latency_us,
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
                return False, {"stage": "complete_communication_path_validity", "reason": reason, "gpu": evidence, "gpu_evidence": gpu_evidence}
        concrete_ok, concrete_paths, concrete_reason = self._concrete_path_evidence(candidate)
        if not concrete_ok:
            return False, {"stage": "complete_communication_path_validity", "reason": concrete_reason, "physical_paths": concrete_paths}
        if len({str(gpu["node_id"]) for gpu in candidate}) > 1:
            required_bandwidth = self.requirements.gpu.min_fabric_bandwidth_gbps
            required_latency = self.requirements.gpu.max_fabric_latency_us
            if required_bandwidth is not None or required_latency is not None:
                selected_uuids = {str(self._payload(gpu).get("gpu_uuid") or "").strip() for gpu in candidate}
                capability_paths = [path for path in concrete_paths if str(path.get("source_gpu") or "").removeprefix("gpu:") in selected_uuids or str(path.get("destination_gpu") or "").removeprefix("gpu:") in selected_uuids]
                eligible_capability_paths = []
                for path in capability_paths:
                    measurement = path.get("measurement")
                    if not isinstance(measurement, dict):
                        continue
                    bandwidth = measurement.get("bandwidth_gbps")
                    latency = measurement.get("latency_us")
                    if required_bandwidth is not None:
                        try:
                            if bandwidth is None or float(bandwidth) < float(required_bandwidth):
                                continue
                        except (TypeError, ValueError):
                            continue
                    if required_latency is not None:
                        try:
                            if latency is None or float(latency) > float(required_latency):
                                continue
                        except (TypeError, ValueError):
                            continue
                    eligible_capability_paths.append(path)
                if not eligible_capability_paths:
                    return False, {"stage": "measured_fabric_capability", "reason": "no_verified_concrete_path_meets_measured_fabric_requirements", "required_bandwidth_gbps": required_bandwidth, "required_latency_us": required_latency, "physical_paths": capability_paths}
        node_ids = tuple(dict.fromkeys(str(gpu["node_id"]) for gpu in candidate))
        node_candidates = [self._node_candidate(node_id, self._node_rows()[node_id]) for node_id in node_ids]
        node_candidates = [item for item in node_candidates if item is not None]
        if len(node_candidates) != len(node_ids):
            return False, {"stage": "resource_eligibility", "reason": "selected_node_is_not_eligible", "node_ids": node_ids}
        shared_network = None
        if len(node_ids) > 1:
            shared_network = self.scheduler._shared_verified_network_domain(node_candidates)
            network_known = any(self._network_domains(candidate) for candidate in node_candidates)
            if network_known and shared_network is None:
                return False, {"stage": "complete_communication_path_validity", "reason": "missing_verified_shared_network_domain", "node_ids": node_ids}
        topology = [{"gpu_id": self._payload(gpu).get("gpu_id"), "gpu_uuid": self._payload(gpu).get("gpu_uuid"), "node_id": gpu["node_id"], "topology_domain": self._payload(gpu).get("topology_domain"), "numa_node": self._payload(gpu).get("numa_node"), "topology_source": self._payload(gpu).get("topology_source")} for gpu in candidate]
        return True, {"gpu_evidence": gpu_evidence, "node_ids": node_ids, "shared_network": shared_network, "topology": topology, "concrete_physical_paths": concrete_paths}

    def _concrete_path_evidence(self, candidate: tuple[dict[str, Any], ...]) -> tuple[bool, list[dict[str, Any]], str]:
        selected = {str(self._payload(gpu).get("gpu_uuid") or "") for gpu in candidate}; selected.discard("")
        if len({str(gpu["node_id"]) for gpu in candidate}) < 2:
            return True, [], "same_node"
        if not self.physical_paths:
            return True, [], "no_canonical_concrete_path_records"
        paths = [path for path in self.physical_paths if str(path.get("state") or "") in {"VERIFIED", "MEASURED", "REVERIFIED"}]
        evidence = [path for path in paths if str(path.get("source_gpu") or "").removeprefix("gpu:") in selected or str(path.get("destination_gpu") or "").removeprefix("gpu:") in selected]
        node_pairs = {tuple(sorted((str(gpu["node_id"]), str(other["node_id"])))) for index, gpu in enumerate(candidate) for other in candidate[index + 1:] if str(gpu["node_id"]) != str(other["node_id"])}
        covered_pairs = set()
        for path in evidence:
            source = str(path.get("source_gpu") or "").removeprefix("gpu:"); destination = str(path.get("destination_gpu") or "").removeprefix("gpu:")
            source_node = next((str(gpu["node_id"]) for gpu in candidate if str(self._payload(gpu).get("gpu_uuid")) == source), None)
            destination_node = next((str(gpu["node_id"]) for gpu in candidate if str(self._payload(gpu).get("gpu_uuid")) == destination), None)
            if source_node and destination_node and source_node != destination_node:
                covered_pairs.add(tuple(sorted((source_node, destination_node))))
        missing = node_pairs - covered_pairs
        return not missing, evidence, "missing_verified_concrete_inter_node_path" if missing else "verified"

    @classmethod
    def _cross_node_gpu_pairs(cls, candidate: tuple[dict[str, Any], ...]) -> tuple[tuple[str, str], ...]:
        """Enumerate every directional cross-node GPU pair required by runtime peers."""
        pairs: list[tuple[str, str]] = []
        for source in candidate:
            source_uuid = str(cls._payload(source).get("gpu_uuid") or "").strip()
            if not source_uuid:
                continue
            for destination in candidate:
                if source is destination or str(source["node_id"]) == str(destination["node_id"]):
                    continue
                destination_uuid = str(cls._payload(destination).get("gpu_uuid") or "").strip()
                if destination_uuid:
                    pairs.append((f"gpu:{source_uuid}", f"gpu:{destination_uuid}"))
        return tuple(pairs)

    def _adaptive_route_selection(self, candidate: tuple[dict[str, Any], ...]) -> tuple[dict[str, str], ...]:
        """Select the observed best measured canonical route for each directional GPU pair."""
        gpu_pairs = self._cross_node_gpu_pairs(candidate)
        if not gpu_pairs:
            return ()
        return AdaptiveFabricRouteSelector.select_for_gpu_pairs(
            self.physical_paths,
            self.route_health,
            gpu_pairs,
        )

    def _adaptive_route_sets(self, candidate: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        """Build an independently evidenced active/standby route set for every direction."""
        gpu_pairs = self._cross_node_gpu_pairs(candidate)
        if not gpu_pairs:
            return ()
        return tuple(
            AdaptiveFabricRouteSelector.select_resilient_route_set(
                self.physical_paths,
                self.route_health,
                pair,
            )
            for pair in gpu_pairs
        )

    def _candidate_predictive_route(self, candidate: tuple[dict[str, Any], ...]) -> tuple[int]:
        """Prefer explicitly evidenced improving routes and defer degrading ones."""
        from .compute_fabric_telemetry import workload_performance_key

        workload = {
            "workload_class": getattr(
                getattr(self.requirements, "workload_class", None),
                "value",
                getattr(self.requirements, "workload_class", None),
            ),
            **dict(getattr(self.requirements, "performance_signature", ()) or ()),
        }
        route_ids = {
            str(route.get("path_id") or "").strip()
            for route in self._adaptive_route_selection(candidate)
            if str(route.get("path_id") or "").strip()
        }
        if not route_ids:
            route_ids = {
                str(path.get("path_id") or "").strip()
                for gpu in candidate
                for path in self._verified_paths(gpu)
                if str(path.get("path_id") or "").strip()
            }

        states = []
        for path in self.physical_paths:
            path_id = str(path.get("path_id") or "").strip()
            if path_id not in route_ids:
                continue
            identity = {
                key: path[key]
                for key in (
                    "node_id", "gpu_uuid", "nic", "nic_pci_bus_id",
                    "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer",
                )
                if path.get(key) is not None and str(path.get(key)).strip()
            }
            workload_key = workload_performance_key(identity, workload) if identity else ""
            health = self.route_health.get(path_id)
            if not isinstance(health, dict):
                health = self.route_health.get(workload_key)
            predictive = (
                health.get("predictive_by_workload_key", {}).get(workload_key)
                if isinstance(health, dict)
                else None
            )
            state = str((predictive or {}).get("state") or "").strip()
            states.append({"improving": 0, "degrading": 2}.get(state, 1))
        return (min(states) if states else 1,)


    def _predictive_failure_details(self, candidate: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        """Return exact observed early-warning evidence for eligible candidate paths."""
        from .compute_fabric_telemetry import workload_performance_key

        workload = {
            "workload_class": getattr(
                getattr(self.requirements, "workload_class", None),
                "value",
                getattr(self.requirements, "workload_class", None),
            ),
            **dict(getattr(self.requirements, "performance_signature", ()) or ()),
        }
        route_ids = {
            str(route.get("path_id") or "").strip()
            for route in self._adaptive_route_selection(candidate)
            if str(route.get("path_id") or "").strip()
        }
        if not route_ids:
            route_ids = {
                str(path.get("path_id") or "").strip()
                for gpu in candidate
                for path in self._verified_paths(gpu)
                if str(path.get("path_id") or "").strip()
            }

        details = []
        for path in self.physical_paths:
            path_id = str(path.get("path_id") or "").strip()
            if path_id not in route_ids:
                continue
            identity = {
                key: path[key]
                for key in (
                    "node_id", "gpu_uuid", "nic", "nic_pci_bus_id",
                    "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer",
                )
                if path.get(key) is not None and str(path.get(key)).strip()
            }
            health = self.route_health.get(path_id)
            if not isinstance(health, dict):
                continue
            workload_key = workload_performance_key(identity, workload) if identity and workload else ""
            predictive = None
            if workload_key:
                predictive = health.get("predictive_failure_by_workload_key", {}).get(workload_key)
            if not isinstance(predictive, dict):
                predictive = health.get("predictive_failure_degradation")
            if not isinstance(predictive, dict):
                continue
            details.append({
                "path_id": path_id,
                "workload_key": workload_key or None,
                "state": str(predictive.get("state") or "insufficient_evidence"),
                "sample_count": int(predictive.get("sample_count", 0) or 0),
                "failure_count": int(predictive.get("failure_count", 0) or 0),
                "consecutive_failures": int(predictive.get("consecutive_failures", 0) or 0),
                "failure_domains": tuple(predictive.get("failure_domains") or ()),
                "evidence": dict(predictive.get("evidence") or {}),
            })
        return tuple(sorted(details, key=lambda item: str(item["path_id"])))

    def _candidate_predictive_failure(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        """Prefer observed stable routes and defer routes showing worsening patterns."""
        details = self._predictive_failure_details(candidate)
        if not details:
            return (1, 0, ())
        rank = {"stable": 0, "insufficient_evidence": 1, "degrading": 2, "failure_pattern": 3}
        best_rank = min(rank.get(str(item["state"]), 1) for item in details)
        best_samples = max(int(item["sample_count"]) for item in details if rank.get(str(item["state"]), 1) == best_rank)
        evidence_ids = tuple(item["path_id"] for item in details if rank.get(str(item["state"]), 1) == best_rank)
        return (best_rank, -best_samples, evidence_ids)

    def _candidate_multidimensional_workload(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        """Prefer candidates with exact observed multidimensional workload evidence."""
        from .compute_fabric_telemetry import workload_performance_key

        workload = {
            "workload_class": getattr(
                getattr(self.requirements, "workload_class", None),
                "value",
                getattr(self.requirements, "workload_class", None),
            ),
            **dict(getattr(self.requirements, "performance_signature", ()) or ()),
        }
        if not workload:
            return (1, 0, ())

        route_ids = {
            str(route.get("path_id") or "").strip()
            for route in self._adaptive_route_selection(candidate)
            if str(route.get("path_id") or "").strip()
        }
        if not route_ids:
            route_ids = {
                str(path.get("path_id") or "").strip()
                for gpu in candidate
                for path in self._verified_paths(gpu)
                if str(path.get("path_id") or "").strip()
            }

        matches = []
        for path in self.physical_paths:
            path_id = str(path.get("path_id") or "").strip()
            if path_id not in route_ids:
                continue
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
            workload_key = workload_performance_key(identity, workload)
            health = getattr(self, "route_health", {}).get(path_id)
            if not isinstance(health, dict):
                continue
            evidence = health.get("multidimensional_by_workload_key", {}).get(workload_key)
            if not isinstance(evidence, dict):
                continue
            sample_count = int(evidence.get("sample_count", 0) or 0)
            dimensions = evidence.get("dimensions")
            if not isinstance(dimensions, dict) or not dimensions:
                continue
            matches.append({
                "path_id": path_id,
                "workload_key": workload_key,
                "sample_count": sample_count,
                "dimensions": dict(sorted(dimensions.items())),
                "observations": tuple(evidence.get("observations") or ()),
            })

        if not matches:
            return (1, 0, ())
        best_samples = max(int(item["sample_count"]) for item in matches)
        evidence_ids = tuple(sorted(str(item["path_id"]) for item in matches))
        return (0, -best_samples, evidence_ids)

    def _candidate_concrete_performance(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        """Rank candidates using only directly observed concrete-path measurements.

        No synthetic score is created. Missing observations sort behind observed
        measurements, and the individual measured dimensions remain visible in the
        returned evidence and decision trace.
        """
        concrete_ok, paths, _ = self._concrete_path_evidence(candidate)
        if not concrete_ok or not paths:
            return (1, float("inf"), float("inf"), 0, "")
        # A REVERIFIED path may retain historical measurement evidence, but that
        # observation is not current performance authority until a fresh MEASURED
        # observation is recorded.
        measurements = [
            path.get("measurement")
            for path in paths
            if str(path.get("state") or "") == "MEASURED"
            and isinstance(path.get("measurement"), dict)
        ]
        if not measurements:
            return (1, float("inf"), float("inf"), 0, "")
        bandwidths = []
        latencies = []
        samples = 0
        freshest = float("-inf")
        for measurement in measurements:
            try:
                if measurement.get("bandwidth_gbps") is not None:
                    bandwidths.append(float(measurement["bandwidth_gbps"]))
                if measurement.get("latency_us") is not None:
                    latencies.append(float(measurement["latency_us"]))
                samples += int(measurement.get("sample_count", 0) or 0)
            except (TypeError, ValueError):
                continue
            try:
                freshest = max(freshest, float(measurement.get("observed_at", float("-inf"))))
            except (TypeError, ValueError):
                pass
        if not bandwidths and not latencies:
            return (1, float("inf"), float("inf"), -samples, "")
        # Direct observations only: lower latency first, then higher bandwidth,
        # then more samples, then newer observations, then deterministic path ID.
        return (0, min(latencies, default=float("inf")), -max(bandwidths, default=0.0), -samples, str(max((str(path.get("path_id") or "") for path in paths), default="")))

    def _candidate_performance(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        observations = []
        for gpu in candidate:
            for path in self._verified_paths(gpu):
                identity = {key: path[key] for key in ("node_id", "gpu_uuid", "nic", "nic_pci_bus_id", "rdma_device", "rdma_port", "rdma_pci_bus_id", "link_layer") if path.get(key) is not None and str(path.get(key)).strip()}
                if not identity:
                    continue
                legacy_key = physical_path_key(identity)
                workload = {"workload_class": getattr(getattr(self.requirements, "workload_class", None), "value", getattr(self.requirements, "workload_class", None)), **dict(getattr(self.requirements, "performance_signature", ()) or ())}
                from .compute_fabric_telemetry import workload_performance_key
                key = workload_performance_key(identity, workload)
                observation = self.performance_history.get(key) or self.performance_history.get(legacy_key)
                if observation is not None:
                    observations.append(observation)
        if not observations:
            return (1, float("inf"), 0)
        elapsed = [float(item.get("avg_all_reduce_elapsed_ms", float("inf"))) for item in observations]
        return (0, sum(elapsed) / len(elapsed), -sum(int(item.get("sample_count", 0)) for item in observations))

    def _candidate_route_health(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        adaptive_routes = self._adaptive_route_selection(candidate)
        if adaptive_routes:
            observations = [
                self.route_health.get(str(route["path_id"]))
                for route in adaptive_routes
            ]
            observations = [item for item in observations if isinstance(item, dict)]
            if observations:
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
        return min((0, float(item.get("latency_delta_from_mean_ms", float("inf"))), float(item.get("failure_rate", float("inf"))), float(item.get("latest_latency_ms", float("inf"))), -int(item.get("sample_count", 0))) for item in observations)

    def _candidate_continuous_optimization(self, candidate: tuple[dict[str, Any], ...]) -> tuple:
        """Prefer candidates that preserve exact future placement flexibility.

        This is deliberately the final adaptive preference. Every candidate has
        already passed hard physical validation and all existing observed
        performance/health intelligence, so capacity preservation cannot override
        stronger evidence.
        """
        from .compute_fabric_telemetry import derive_continuous_optimization_evidence

        selected_keys = {str(row.get("resource_key") or "") for row in candidate}
        required = int(self.requirements.gpu.gpu_count)
        compatible = self._compatible_gpu_rows(self.rows)

        by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for gpu in compatible:
            key = (str(gpu.get("provider_id") or ""), str(gpu.get("domain_id") or ""))
            by_scope.setdefault(key, []).append(gpu)

        future_single_node_count = 0
        future_feasible_domain_count = 0
        for scope_rows in by_scope.values():
            remaining = [
                gpu for gpu in scope_rows
                if str(gpu.get("resource_key") or "") not in selected_keys
            ]
            by_node: dict[str, list[dict[str, Any]]] = {}
            for gpu in remaining:
                by_node.setdefault(str(gpu.get("node_id") or ""), []).append(gpu)

            future_single_node_count += sum(
                1 for gpu_rows in by_node.values()
                if len(gpu_rows) >= required
            )

            if self.requirements.workload_class.value == "multi_node_gpu":
                node_domain_members: dict[str, set[str]] = {}
                for node_id, gpu_rows in by_node.items():
                    node_row_group = self._node_rows().get(node_id, [])
                    node = self._node_candidate(node_id, node_row_group)
                    if node is None:
                        continue
                    domains = self._network_domains(node)
                    for domain in domains:
                        node_domain_members.setdefault(str(domain), set()).add(node_id)
                for domain, node_ids in node_domain_members.items():
                    total = sum(len(by_node.get(node_id, ())) for node_id in node_ids)
                    if len(node_ids) >= 2 and total >= required:
                        future_feasible_domain_count += 1

        current_performance = self._candidate_performance(candidate)
        observed_latency = None
        if current_performance and int(current_performance[0]) == 0:
            try:
                value = float(current_performance[1])
                if value != float("inf"):
                    observed_latency = value
            except (TypeError, ValueError):
                observed_latency = None

        candidate_key = "|".join(self._stable_key(candidate))
        optimization = derive_continuous_optimization_evidence((
            {
                "candidate_key": candidate_key,
                "observed_latency_ms": observed_latency,
                "future_feasible_domain_count": future_feasible_domain_count,
                "future_single_node_count": future_single_node_count,
                "sample_count": int(-current_performance[2]) if current_performance and len(current_performance) > 2 and current_performance[0] == 0 else 0,
            },
        ))
        state = str(optimization.get("state") or "insufficient_evidence")
        capacity_rank = (
            0 if state in {"balanced", "capacity_preservation"} else
            1 if state == "performance_preference" else 2
        )
        return (
            capacity_rank,
            -future_feasible_domain_count,
            -future_single_node_count,
            candidate_key,
        )

    def _candidate_continuous_optimization_details(self, candidates: list[tuple[dict[str, Any], ...]]) -> dict[str, Any]:
        """Return the exact optimization evidence for all already-valid candidates."""
        records = []
        for candidate in candidates:
            key = "|".join(self._stable_key(candidate))
            rank = self._candidate_performance(candidate)
            latency = None
            samples = 0
            if rank and int(rank[0]) == 0:
                try:
                    latency = float(rank[1])
                    if latency == float("inf"):
                        latency = None
                except (TypeError, ValueError):
                    latency = None
                try:
                    samples = int(-rank[2])
                except (TypeError, ValueError):
                    samples = 0
            optimization_key = self._candidate_continuous_optimization(candidate)
            records.append({
                "candidate_key": key,
                "observed_latency_ms": latency,
                "sample_count": samples,
                "optimization_key": optimization_key,
                "capacity_rank": optimization_key[0],
                "future_feasible_domain_count": -optimization_key[1],
                "future_single_node_count": -optimization_key[2],
            })
        return {
            "candidate_count": len(records),
            "candidates": tuple(sorted(records, key=lambda item: item["candidate_key"])),
        }

    def _stable_key(self, candidate: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        return tuple(sorted(str(row["resource_key"]) for row in candidate))

    def _rank_gpu_rows(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates = list(rows)
        return sorted(candidates, key=lambda gpu: (self.scheduler._gpu_placement_structure_key(gpu, candidates), self.scheduler._gpu_performance_key(gpu, self.performance_history, self.requirements), self.scheduler._gpu_route_health_key(gpu, self.route_health), str(gpu.get("resource_key") or "")))

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
                    self._trace("complete_communication_path_validity", "rejected", reason=reason, resource_keys=(str(gpu["resource_key"],),), evidence=evidence)
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
        viable_groups = [group for group in provider_groups.values() if len(group) >= 2 and sum(len(node["gpus"]) for node in group) >= needed]
        if not viable_groups:
            self._trace("resource_eligibility", "rejected", reason="no_provider_and_domain_can_satisfy_complete_placement")
            raise RuntimeError("no provider and domain can satisfy complete placement")
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
            network_group_options.sort(key=lambda item: (-sum(len(node["gpus"]) for node in item[1]), -sum(self.scheduler._node_topology_score(node)[0] for node in item[1]), str(item[0])))
            ranked_group = network_group_options[0][1]
        else:
            ranked_group = max(viable_groups, key=lambda group: (sum(len(node["gpus"]) for node in group), tuple(sorted(str(node["node_id"]) for node in group))))
        ranked_nodes = sorted(ranked_group, key=lambda node: (tuple(-value for value in self.scheduler._node_topology_score(node)), self.scheduler._gpu_performance_key(node["gpus"][0], self.performance_history, self.requirements), self.scheduler._gpu_route_health_key(node["gpus"][0], self.route_health), str(node["node_id"])))
        selected_nodes = []; total = 0
        for node in ranked_nodes:
            selected_nodes.append(node); total += len(node["gpus"])
            if len(selected_nodes) >= 2 and total >= needed:
                break
        if len(selected_nodes) < 2 or total < needed:
            return
        selected: list[dict[str, Any]] = []; remaining = needed
        for node in selected_nodes:
            take = min(remaining, len(node["gpus"])); selected.extend(node["gpus"][:take]); remaining -= take
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
                self._trace("resource_eligibility", "rejected", node_id=node_id, reason="node_not_eligible"); continue
            if not node["gpus"]:
                self._trace("capability_compatibility", "rejected", node_id=node_id, reason="no_compatible_gpu"); continue
            nodes.append(node)
        if not nodes:
            raise RuntimeError("no eligible GPU placement candidates")
        valid: list[tuple[tuple[dict[str, Any], ...], dict[str, Any]]] = []; candidate_evidence: list[dict[str, Any]] = []; rejection_count = 0
        for candidate in self._candidate_sets(nodes):
            valid_candidate, evidence = self._valid_candidate(candidate)
            if not valid_candidate:
                rejection_count += 1; rejection = {"status": "rejected", "resource_keys": self._stable_key(candidate), "stage": evidence["stage"], "reason": evidence["reason"], "evidence": evidence}; candidate_evidence.append(rejection); self._trace(evidence["stage"], "rejected", reason=evidence["reason"], resource_keys=self._stable_key(candidate)); continue
            accepted = {"status": "accepted", "resource_keys": self._stable_key(candidate), "evidence": evidence}; candidate_evidence.append(accepted); valid.append((candidate, evidence)); self._trace("complete_physical_validation", "accepted", resource_keys=self._stable_key(candidate))
        if not valid:
            self._trace("complete_physical_validation", "rejected", reason="no_complete_physical_placement", rejected_candidates=rejection_count)
            raise RuntimeError("no complete physical placement")
        ranked = sorted(valid, key=lambda item: (self._candidate_performance(item[0]), self._candidate_route_health(item[0]), self._candidate_predictive_route(item[0]), self._candidate_predictive_failure(item[0]), self._candidate_multidimensional_workload(item[0]), self._candidate_concrete_performance(item[0]), self._stable_key(item[0])))
        selected, evidence = ranked[0]
        self._trace("workload_performance", "applied", key=self._candidate_performance(selected)); self._trace("route_health", "applied", key=self._candidate_route_health(selected)); self._trace("predictive_route_evidence", "applied", key=self._candidate_predictive_route(selected)); self._trace("predictive_failure_degradation", "applied", key=self._candidate_predictive_failure(selected), evidence=self._predictive_failure_details(selected)); self._trace("multidimensional_workload_evidence", "applied", key=self._candidate_multidimensional_workload(selected)); adaptive_routes = self._adaptive_route_selection(selected); adaptive_route_sets = self._adaptive_route_sets(selected); self._trace("adaptive_route_selection", "applied", selected_routes=adaptive_routes, route_sets=adaptive_route_sets); self._trace("concrete_path_performance", "applied", key=self._candidate_concrete_performance(selected)); self._trace("stable_resource_ordering", "applied", resource_keys=self._stable_key(selected))
        provider_ids = {str(row["provider_id"]) for row in selected}; domain_ids = {str(row["domain_id"]) for row in selected}
        if len(provider_ids) != 1 or len(domain_ids) != 1:
            raise RuntimeError("complete placement must remain within one provider and domain")
        gpu_ids = tuple(sorted(f'{row["node_id"]}/{self._payload(row).get("gpu_id")}' for row in selected)); node_ids = tuple(sorted({str(row["node_id"]) for row in selected})); resource_keys = tuple(sorted(str(row["resource_key"]) for row in selected))
        path_evidence = []; locality = []
        for row in selected:
            payload = self._payload(row); path_evidence.extend(self._verified_paths(row)); locality.extend(self.scheduler._gpu_nic_locality_evidence(row, payload.get("gpu_uuid")))
        workload_signature = tuple(getattr(self.requirements, "performance_signature", ()) or ())
        stable_identity = {"provider_id": next(iter(provider_ids)), "domain_id": next(iter(domain_ids)), "workload_class": getattr(getattr(self.requirements, "workload_class", None), "value", getattr(self.requirements, "workload_class", None)), "workload_signature": workload_signature, "gpu_requirements": {"gpu_count": self.requirements.gpu.gpu_count, "min_vram_bytes": self.requirements.gpu.min_vram_bytes, "min_compute_capability": self.requirements.gpu.min_compute_capability, "required_cuda_version": self.requirements.gpu.required_cuda_version, "required_driver_version": self.requirements.gpu.required_driver_version, "required_nvlink_domain": self.requirements.gpu.required_nvlink_domain, "require_nccl": self.requirements.gpu.require_nccl, "min_fabric_bandwidth_gbps": self.requirements.gpu.min_fabric_bandwidth_gbps, "max_fabric_latency_us": self.requirements.gpu.max_fabric_latency_us, "require_redundant_fabric_path": self.requirements.gpu.require_redundant_fabric_path}, "min_cpu_count": self.requirements.min_cpu_count, "min_memory_bytes": self.requirements.min_memory_bytes, "same_node": self.requirements.same_node, "topology_domain": self.requirements.topology_domain, "allowed_node_ids": tuple(self.requirements.allowed_node_ids), "gpu_ids": gpu_ids, "node_ids": node_ids, "resource_keys": resource_keys, "paths": [{key: path.get(key) for key in sorted(path) if key not in {"verified_rdma_link", "bandwidth_gbps", "latency_us"}} for path in path_evidence], "adaptive_routes": adaptive_routes, "adaptive_route_sets": adaptive_route_sets}
        placement_id = hashlib.sha256(json.dumps(stable_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return PlacementDecision(placement_id=placement_id, provider_id=next(iter(provider_ids)), domain_id=next(iter(domain_ids)), workload_signature=workload_signature, selected_gpu_ids=gpu_ids, selected_node_ids=node_ids, selected_resource_keys=resource_keys, evidence={"physical_paths": path_evidence, "gpu_nic_rdma": locality, "topology": evidence["topology"], "shared_network": evidence["shared_network"], "concrete_physical_paths": evidence.get("concrete_physical_paths", []), "workload_performance": self._candidate_performance(selected), "route_health": self._candidate_route_health(selected), "predictive_route_evidence": self._candidate_predictive_route(selected), "predictive_failure_degradation": {"key": self._candidate_predictive_failure(selected), "evidence": self._predictive_failure_details(selected)}, "multidimensional_workload_evidence": self._candidate_multidimensional_workload(selected), "concrete_path_performance": self._candidate_concrete_performance(selected), "adaptive_routes": adaptive_routes, "adaptive_route_sets": adaptive_route_sets, "candidate_evaluations": candidate_evidence, "rejection_count": rejection_count}, decision_trace=tuple(self.trace))