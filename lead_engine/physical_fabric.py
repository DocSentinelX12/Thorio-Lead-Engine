from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import itertools
import json
from typing import Mapping, Sequence


class FabricPathState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CONSTRUCTED = "CONSTRUCTED"
    VERIFIED = "VERIFIED"
    MEASURED = "MEASURED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RECOVERED = "RECOVERED"
    REVERIFIED = "REVERIFIED"


@dataclass(frozen=True)
class PhysicalFabricPath:
    path_id: str
    source_gpu: str
    destination_gpu: str
    segments: tuple[str, ...]
    fabric_domains: tuple[str, ...]
    state: FabricPathState = FabricPathState.CONSTRUCTED


@dataclass(frozen=True)
class FabricVerificationResult:
    path_id: str
    state: FabricPathState
    reason: str | None = None
    failure_domain: str | None = None
    history: tuple[dict[str, object], ...] = ()
    measurement: Mapping[str, object] = field(default_factory=dict)
    measurement_observed_at: float | None = None
    required_segments: tuple[str, ...] = ()


def _path_id(source_gpu: str, destination_gpu: str, segments: Sequence[str], fabric_domains: Sequence[str]) -> str:
    material = json.dumps(
        {
            "source_gpu": source_gpu,
            "destination_gpu": destination_gpu,
            "segments": list(segments),
            "fabric_domains": list(fabric_domains),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


class PhysicalFabricPathBuilder:
    """Build exact concrete physical paths from evidence-backed graph edges."""

    _EDGE_TYPES = {
        "gpu_to_pci": ("gpu", "pci"),
        "gpu_to_numa": ("gpu", "numa"),
        "gpu_to_nic": ("gpu", "nic"),
        "nic_to_rdma_device": ("nic", "rdma_device"),
        "rdma_device_to_port": ("rdma_device", "rdma_port"),
        "rdma_port_to_fabric": ("rdma_port", "fabric"),
        "fabric_to_rdma_port": ("fabric", "rdma_port"),
    }

    @classmethod
    def build(
        cls,
        *,
        locality_graph: Mapping[str, object],
        source_gpu: str,
        destination_gpu: str,
    ) -> tuple[PhysicalFabricPath, ...]:
        raw_components = locality_graph.get("components", ())
        raw_edges = locality_graph.get("edges", ())
        component_types: dict[str, str] = {}
        for raw in raw_components if isinstance(raw_components, Sequence) else ():
            if not isinstance(raw, Mapping):
                continue
            identity = str(raw.get("identity") or "").strip()
            component_type = str(raw.get("component_type") or "").strip()
            if identity and component_type:
                existing = component_types.get(identity)
                if existing is not None and existing != component_type:
                    component_types[identity] = "conflict"
                else:
                    component_types[identity] = component_type

        adjacency: dict[tuple[str, str], set[str]] = {}
        for raw in raw_edges if isinstance(raw_edges, Sequence) else ():
            if not isinstance(raw, Mapping):
                continue
            if str(raw.get("state") or "").strip().lower() != "known":
                continue
            kind = str(raw.get("relationship_type") or "").strip()
            source = str(raw.get("source") or "").strip()
            target = str(raw.get("target") or "").strip()
            expected = cls._EDGE_TYPES.get(kind)
            if not expected or not source or not target:
                continue
            if component_types.get(source) != expected[0] or component_types.get(target) != expected[1]:
                continue
            adjacency.setdefault((kind, source), set()).add(target)

        def targets(kind: str, source: str) -> tuple[str, ...]:
            return tuple(sorted(adjacency.get((kind, source), set())))

        def reverse_targets(kind: str, target: str) -> tuple[str, ...]:
            return tuple(sorted(source for (edge_kind, source), values in adjacency.items() if edge_kind == kind and target in values))

        source_pci = targets("gpu_to_pci", source_gpu)
        source_numa = targets("gpu_to_numa", source_gpu)
        source_nics = targets("gpu_to_nic", source_gpu)
        destination_pci = targets("gpu_to_pci", destination_gpu)
        destination_numa = targets("gpu_to_numa", destination_gpu)
        destination_nics = targets("gpu_to_nic", destination_gpu)
        if not source_nics or not destination_nics:
            return ()

        source_locality = tuple(itertools.product(source_pci or (None,), source_numa or (None,), source_nics))
        destination_locality = tuple(itertools.product(destination_nics, destination_numa or (None,), destination_pci or (None,)))
        paths: dict[str, PhysicalFabricPath] = {}

        for source_pci_id, source_numa_id, source_nic in source_locality:
            for source_rdma in targets("nic_to_rdma_device", source_nic):
                for source_port in targets("rdma_device_to_port", source_rdma):
                    for fabric in targets("rdma_port_to_fabric", source_port):
                        for destination_port in targets("fabric_to_rdma_port", fabric):
                            for destination_rdma in reverse_targets("rdma_device_to_port", destination_port):
                                for destination_nic in reverse_targets("nic_to_rdma_device", destination_rdma):
                                    if destination_nic not in destination_nics:
                                        continue
                                    for dst_nic, dst_numa, dst_pci in destination_locality:
                                        if dst_nic != destination_nic:
                                            continue
                                        segments = tuple(
                                            segment
                                            for segment in (
                                                source_gpu,
                                                source_pci_id,
                                                source_numa_id,
                                                source_nic,
                                                source_rdma,
                                                source_port,
                                                fabric,
                                                destination_port,
                                                destination_rdma,
                                                destination_nic,
                                                dst_numa,
                                                dst_pci,
                                                destination_gpu,
                                            )
                                            if segment is not None
                                        )
                                        if any(component_types.get(segment) in (None, "conflict") for segment in segments):
                                            continue
                                        path = PhysicalFabricPath(
                                            path_id=_path_id(source_gpu, destination_gpu, segments, (fabric,)),
                                            source_gpu=source_gpu,
                                            destination_gpu=destination_gpu,
                                            segments=segments,
                                            fabric_domains=(fabric,),
                                        )
                                        paths[path.path_id] = path
        return tuple(paths[key] for key in sorted(paths))


class PhysicalFabricVerification:
    @staticmethod
    def verify(path: PhysicalFabricPath, *, evidence: Sequence[Mapping[str, object]]) -> FabricVerificationResult:
        covered = {
            str(item.get("segment"))
            for item in evidence
            if str(item.get("result") or "").lower() == "pass" and item.get("segment")
        }
        required = set(path.segments)
        if not required.issubset(covered):
            return FabricVerificationResult(
                path_id=path.path_id,
                state=FabricPathState.CONSTRUCTED,
                reason="required path-segment evidence is incomplete",
                required_segments=path.segments,
            )
        return FabricVerificationResult(path_id=path.path_id, state=FabricPathState.VERIFIED, required_segments=path.segments)

    @staticmethod
    def measure(verification: FabricVerificationResult, *, measurement: Mapping[str, object], observed_at: float | None = None) -> FabricVerificationResult:
        if verification.state not in (FabricPathState.VERIFIED, FabricPathState.REVERIFIED, FabricPathState.MEASURED):
            return verification
        if (
            verification.state is FabricPathState.MEASURED
            and observed_at is not None
            and verification.measurement_observed_at is not None
            and float(observed_at) <= float(verification.measurement_observed_at)
        ):
            return verification
        if str(measurement.get("status") or "").strip().lower() == "degraded":
            reason = str(measurement.get("degradation_reason") or "").strip()
            failure_domain = str(measurement.get("failure_domain") or "").strip()
            if reason and failure_domain:
                degraded = PhysicalFabricVerification.degrade(verification, reason=reason, failure_domain=failure_domain)
                return FabricVerificationResult(
                    path_id=degraded.path_id,
                    state=degraded.state,
                    reason=degraded.reason,
                    failure_domain=degraded.failure_domain,
                    history=degraded.history,
                    measurement=dict(measurement),
                    measurement_observed_at=observed_at if observed_at is not None else verification.measurement_observed_at,
                    required_segments=degraded.required_segments,
                )
        history = verification.history + ((
            {
                "state": verification.state.value,
                "reason": "fresh post-recovery measurement",
                "failure_domain": verification.failure_domain,
                "prior_measurement": dict(verification.measurement),
            },
        ) if verification.state is FabricPathState.REVERIFIED else ())
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.MEASURED,
            history=history,
            measurement=dict(measurement),
            measurement_observed_at=observed_at if observed_at is not None else verification.measurement_observed_at,
            required_segments=verification.required_segments,
        )

    @staticmethod
    def degrade(verification: FabricVerificationResult, *, reason: str, failure_domain: str) -> FabricVerificationResult:
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.DEGRADED,
            reason=reason,
            failure_domain=failure_domain,
            history=verification.history + (({"state": verification.state.value, "reason": reason, "failure_domain": failure_domain},)),
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )

    @staticmethod
    def recover(verification: FabricVerificationResult) -> FabricVerificationResult:
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.RECOVERED,
            history=verification.history + (({"state": verification.state.value, "reason": verification.reason, "failure_domain": verification.failure_domain},)),
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )

    @staticmethod
    def fail(verification: FabricVerificationResult, *, reason: str, failure_domain: str) -> FabricVerificationResult:
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.FAILED,
            reason=reason,
            failure_domain=failure_domain,
            history=verification.history + (({"state": verification.state.value, "reason": reason, "failure_domain": failure_domain, "measurement": dict(verification.measurement)},)),
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )

    @staticmethod
    def reverify(verification: FabricVerificationResult, *, evidence: Sequence[Mapping[str, object]]) -> FabricVerificationResult:
        covered = {
            str(item.get("segment"))
            for item in evidence
            if str(item.get("result") or "").lower() == "pass" and item.get("segment")
        }
        required = set(verification.required_segments)
        complete = bool(required) and required.issubset(covered)
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.REVERIFIED if complete else verification.state,
            reason=None if complete else "fresh path-segment evidence is incomplete",
            history=verification.history + (({"state": verification.state.value, "reason": verification.reason, "fresh_evidence_segments": sorted(covered)},)),
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )


def resolve_observed_fabric_path_id(paths: Sequence[Mapping[str, object]], *, source_gpu: str, destination_gpu: str, source_rdma_device: str, source_rdma_port: int, destination_rdma_device: str, destination_rdma_port: int) -> str | None:
    source_gpu = str(source_gpu).strip()
    destination_gpu = str(destination_gpu).strip()
    source_rdma_device = str(source_rdma_device).strip()
    destination_rdma_device = str(destination_rdma_device).strip()
    if not source_gpu or not destination_gpu or not source_rdma_device or not destination_rdma_device:
        return None
    if not isinstance(source_rdma_port, int) or source_rdma_port < 1 or not isinstance(destination_rdma_port, int) or destination_rdma_port < 1:
        return None
    source_port = f"rdma:{source_rdma_device}:{source_rdma_port}"
    destination_port = f"rdma:{destination_rdma_device}:{destination_rdma_port}"
    matches = []
    for raw in paths:
        if not isinstance(raw, Mapping):
            continue
        path_id = str(raw.get("path_id") or "").strip()
        segments = raw.get("segments")
        if not path_id or str(raw.get("source_gpu") or "").strip() != source_gpu or str(raw.get("destination_gpu") or "").strip() != destination_gpu or not isinstance(segments, (list, tuple)):
            continue
        normalized = {str(segment).strip() for segment in segments if str(segment).strip()}
        if source_port in normalized and destination_port in normalized:
            matches.append(path_id)
    return matches[0] if len(matches) == 1 else None


class AdaptiveFabricRouteSelector:
    _ELIGIBLE_STATES = frozenset({FabricPathState.VERIFIED.value, FabricPathState.MEASURED.value, FabricPathState.REVERIFIED.value})

    @classmethod
    def _candidates(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
        candidates = []
        for raw in paths:
            path_id = str(raw.get("path_id") or "").strip()
            state = str(raw.get("state") or "").strip()
            health = route_health.get(path_id)
            measurement = raw.get("measurement")
            if not path_id or state not in cls._ELIGIBLE_STATES or state != FabricPathState.MEASURED.value or not isinstance(health, Mapping) or not isinstance(measurement, Mapping):
                continue
            candidates.append({"path_id": path_id, "health": dict(health), "measurement": dict(measurement), "state": state})
        return candidates

    @classmethod
    def _key(cls, candidate: Mapping[str, object]) -> tuple[float, float, float, float, str]:
        health = candidate["health"]
        assert isinstance(health, Mapping)
        return (
            float(health.get("failure_rate", float("inf"))),
            float(health.get("latency_delta_from_mean_ms", float("inf"))),
            float(health.get("latest_latency_ms", float("inf"))),
            -float(health.get("sample_count", 0) or 0),
            str(candidate["path_id"]),
        )

    @classmethod
    def select(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
        candidates = sorted(cls._candidates(paths, route_health), key=cls._key)
        if not candidates:
            return {"path_id": None, "selection_reason": "no_current_measured_route", "alternatives": (), "evidence": ()}
        selected = candidates[0]
        return {
            "path_id": selected["path_id"],
            "selection_reason": "observed_route_health",
            "alternatives": tuple(str(item["path_id"]) for item in candidates[1:]),
            "evidence": tuple({"path_id": str(item["path_id"]), "health": dict(item["health"]), "measurement": dict(item["measurement"])} for item in candidates),
        }

    @classmethod
    def select_resilient_route_set(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]], gpu_pair: tuple[str, str], *, current_path_id: str | None = None) -> dict[str, object]:
        source_gpu, destination_gpu = gpu_pair
        pair_paths = tuple(path for path in paths if str(path.get("source_gpu") or "") == str(source_gpu) and str(path.get("destination_gpu") or "") == str(destination_gpu))
        selection = cls.select(pair_paths, route_health)
        active_path_id = str(selection["path_id"]) if selection["path_id"] is not None else None
        if active_path_id is None:
            return {"source_gpu": str(source_gpu), "destination_gpu": str(destination_gpu), "active_path_id": None, "standby_path_ids": (), "verified_path_ids": (), "selection_reason": str(selection["selection_reason"]), "evidence": ()}
        active_path = next((path for path in pair_paths if str(path.get("path_id") or "") == active_path_id), None)
        if not isinstance(active_path, Mapping):
            return {"source_gpu": str(source_gpu), "destination_gpu": str(destination_gpu), "active_path_id": active_path_id, "standby_path_ids": (), "verified_path_ids": (active_path_id,), "selection_reason": str(selection["selection_reason"]), "evidence": tuple(selection["evidence"])}
        candidates = cls._candidates(pair_paths, route_health)
        path_by_id = {str(path.get("path_id") or ""): path for path in pair_paths if str(path.get("path_id") or "")}
        standby_ids = tuple(str(candidate["path_id"]) for candidate in candidates if str(candidate["path_id"]) != active_path_id and cls.failure_domain_independent(active_path, path_by_id[str(candidate["path_id"])]))
        return {"source_gpu": str(source_gpu), "destination_gpu": str(destination_gpu), "active_path_id": active_path_id, "standby_path_ids": standby_ids, "verified_path_ids": (active_path_id, *standby_ids), "selection_reason": str(selection["selection_reason"]), "current_path_id": str(current_path_id) if current_path_id is not None else None, "evidence": tuple(selection["evidence"])}

    @classmethod
    def select_for_gpu_pairs(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]], gpu_pairs: Sequence[tuple[str, str]]) -> tuple[dict[str, str], ...]:
        selected = []
        for source_gpu, destination_gpu in gpu_pairs:
            decision = cls.select(tuple(path for path in paths if str(path.get("source_gpu") or "") == str(source_gpu) and str(path.get("destination_gpu") or "") == str(destination_gpu)), route_health)
            path_id = decision.get("path_id")
            if path_id is not None:
                selected.append({"source_gpu": str(source_gpu), "destination_gpu": str(destination_gpu), "path_id": str(path_id)})
        return tuple(selected)

    @staticmethod
    def _failure_domain_components(path: Mapping[str, object]) -> frozenset[str]:
        segments, domains = path.get("segments"), path.get("fabric_domains")
        if not isinstance(segments, (list, tuple)) or not isinstance(domains, (list, tuple)):
            return frozenset()
        normalized_segments = frozenset(str(segment).strip() for segment in segments if str(segment).strip())
        normalized_domains = frozenset(str(domain).strip() for domain in domains if str(domain).strip())
        if not normalized_domains:
            return frozenset()
        return frozenset(segment for segment in normalized_segments if segment.startswith("nic:") or (segment.startswith("rdma:") and segment.count(":") == 1)) | normalized_domains

    @classmethod
    def failure_domain_independent(cls, first: Mapping[str, object], second: Mapping[str, object]) -> bool:
        first_domains, second_domains = first.get("fabric_domains"), second.get("fabric_domains")
        if not isinstance(first_domains, (list, tuple)) or not isinstance(second_domains, (list, tuple)):
            return False
        first_domain_set = frozenset(str(item).strip() for item in first_domains if str(item).strip())
        second_domain_set = frozenset(str(item).strip() for item in second_domains if str(item).strip())
        first_components = cls._failure_domain_components(first)
        second_components = cls._failure_domain_components(second)
        return bool(first_domain_set and second_domain_set and first_components and second_components) and not first_domain_set.intersection(second_domain_set) and not first_components.intersection(second_components)

    @classmethod
    def failover_after_exact_path_failure(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]], *, failed_path_id: str, gpu_pair: tuple[str, str]) -> dict[str, object]:
        source_gpu, destination_gpu = gpu_pair
        pair_paths = tuple(path for path in paths if str(path.get("source_gpu") or "") == str(source_gpu) and str(path.get("destination_gpu") or "") == str(destination_gpu))
        failed = next((path for path in pair_paths if str(path.get("path_id") or "") == str(failed_path_id)), None)
        if not isinstance(failed, Mapping):
            return {"migrate": False, "from_path_id": str(failed_path_id), "to_path_id": None, "reason": "failed_path_not_found"}
        independent = tuple(path for path in pair_paths if str(path.get("path_id") or "") != str(failed_path_id) and cls.failure_domain_independent(failed, path))
        selection = cls.select(independent, route_health)
        selected = selection.get("path_id")
        return {"migrate": selected is not None, "from_path_id": str(failed_path_id), "to_path_id": str(selected) if selected is not None else None, "reason": "exact_path_failure_independent_standby" if selected is not None else "no_independently_verified_standby"}

    @classmethod
    def orchestrate_exact_path_recovery(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]], *, failed_path_id: str, gpu_pair: tuple[str, str], attempt_id: str, placement_id: str, generation: int) -> dict[str, object]:
        decision = cls.failover_after_exact_path_failure(paths, route_health, failed_path_id=failed_path_id, gpu_pair=gpu_pair)
        return decision | {"attempt_id": str(attempt_id), "placement_id": str(placement_id), "generation": int(generation)}

    @classmethod
    def adaptive_replacement_plan(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]], current_routes: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
        plan = []
        for route in current_routes:
            if not isinstance(route, Mapping):
                continue
            source_gpu = str(route.get("source_gpu") or "").strip()
            destination_gpu = str(route.get("destination_gpu") or "").strip()
            current_path_id = str(route.get("current_path_id") or "").strip()
            if not source_gpu or not destination_gpu or not current_path_id:
                continue
            pair_paths = tuple(path for path in paths if str(path.get("source_gpu") or "") == source_gpu and str(path.get("destination_gpu") or "") == destination_gpu)
            current = next((path for path in pair_paths if str(path.get("path_id") or "") == current_path_id), None)
            if isinstance(current, Mapping) and current.get("fabric_domains") and current.get("segments"):
                pair_paths = tuple(path for path in pair_paths if str(path.get("path_id") or "") == current_path_id or cls.failure_domain_independent(current, path))
            decision = cls.migration(pair_paths, route_health, current_path_id=current_path_id)
            plan.append({"source_gpu": source_gpu, "destination_gpu": destination_gpu, "from_path_id": str(decision["from_path_id"]), "to_path_id": str(decision["to_path_id"]) if decision["to_path_id"] is not None else None, "migrate": bool(decision["migrate"]), "reason": str(decision["reason"])})
        return tuple(plan)

    @classmethod
    def migration(cls, paths: Sequence[Mapping[str, object]], route_health: Mapping[str, Mapping[str, object]], *, current_path_id: str) -> dict[str, object]:
        selection = cls.select(paths, route_health)
        selected = selection["path_id"]
        if selected is None:
            return {"migrate": False, "from_path_id": current_path_id, "to_path_id": None, "reason": "no_verified_alternative"}
        if str(selected) == str(current_path_id):
            return {"migrate": False, "from_path_id": current_path_id, "to_path_id": current_path_id, "reason": "current_route_remains_selected"}
        return {"migrate": True, "from_path_id": current_path_id, "to_path_id": str(selected), "reason": str(selection["selection_reason"])}
