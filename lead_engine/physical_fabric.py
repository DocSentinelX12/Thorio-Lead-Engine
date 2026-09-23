from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
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


def _path_id(
    source_gpu: str,
    destination_gpu: str,
    segments: Sequence[str],
    fabric_domains: Sequence[str],
) -> str:
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
    _LOCAL_STAGES = (
        ("gpu_to_pci", "pci"),
        ("gpu_to_numa", "numa"),
        ("gpu_to_nic", "nic"),
    )

    @classmethod
    def build(
        cls,
        *,
        locality_graph: Mapping[str, object],
        source_gpu: str,
        destination_gpu: str,
    ) -> tuple[PhysicalFabricPath, ...]:
        edges = locality_graph.get("edges", ())
        components = locality_graph.get("components", ())
        component_types = {
            str(component["identity"]): str(component["component_type"])
            for component in components
            if isinstance(component, Mapping)
            and component.get("identity")
            and component.get("component_type")
        }
        adjacency: dict[tuple[str, str], list[str]] = {}
        for raw in edges:
            if not isinstance(raw, Mapping):
                continue
            if str(raw.get("state") or "") != "known":
                continue
            source = str(raw.get("source") or "")
            target = str(raw.get("target") or "")
            kind = str(raw.get("relationship_type") or "")
            if not source or not target or not kind:
                continue
            adjacency.setdefault((kind, source), []).append(target)

        def targets(kind: str, source: str) -> tuple[str, ...]:
            return tuple(sorted(set(adjacency.get((kind, source), ()))))

        source_pci = targets("gpu_to_pci", source_gpu)
        source_numa = targets("gpu_to_numa", source_gpu)
        source_nics = targets("gpu_to_nic", source_gpu)
        destination_pci = targets("gpu_to_pci", destination_gpu)
        destination_numa = targets("gpu_to_numa", destination_gpu)
        destination_nics = targets("gpu_to_nic", destination_gpu)

        if not source_nics or not destination_nics:
            return ()

        paths: dict[str, PhysicalFabricPath] = {}
        for source_nic in source_nics:
            for source_rdma in targets("nic_to_rdma_device", source_nic):
                for source_port in targets("rdma_device_to_port", source_rdma):
                    for fabric in targets("rdma_port_to_fabric", source_port):
                        for destination_port in targets("fabric_to_rdma_port", fabric):
                            for destination_rdma in cls._reverse_targets(
                                adjacency, "rdma_device_to_port", destination_port
                            ):
                                for destination_nic in cls._reverse_targets(
                                    adjacency, "nic_to_rdma_device", destination_rdma
                                ):
                                    if destination_nic not in destination_nics:
                                        continue
                                    segments = (
                                        source_gpu,
                                        *source_pci,
                                        *source_numa,
                                        source_nic,
                                        source_rdma,
                                        source_port,
                                        fabric,
                                        destination_port,
                                        destination_rdma,
                                        destination_nic,
                                        *destination_numa,
                                        *destination_pci,
                                        destination_gpu,
                                    )
                                    if any(not component_types.get(segment) for segment in segments):
                                        continue
                                    path = PhysicalFabricPath(
                                        path_id=_path_id(
                                            source_gpu,
                                            destination_gpu,
                                            segments,
                                            (fabric,),
                                        ),
                                        source_gpu=source_gpu,
                                        destination_gpu=destination_gpu,
                                        segments=segments,
                                        fabric_domains=(fabric,),
                                    )
                                    paths[path.path_id] = path
        return tuple(paths[key] for key in sorted(paths))

    @staticmethod
    def _reverse_targets(
        adjacency: Mapping[tuple[str, str], Sequence[str]],
        relationship_type: str,
        target: str,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                source
                for (kind, source), targets in adjacency.items()
                if kind == relationship_type and target in targets
            )
        )


class PhysicalFabricVerification:
    @staticmethod
    def verify(
        path: PhysicalFabricPath,
        *,
        evidence: Sequence[Mapping[str, object]],
    ) -> FabricVerificationResult:
        covered = {
            str(item.get("segment"))
            for item in evidence
            if str(item.get("result") or "").lower() == "pass"
            and item.get("segment")
        }
        required = set(path.segments)
        if not required.issubset(covered):
            return FabricVerificationResult(
                path_id=path.path_id,
                state=FabricPathState.CONSTRUCTED,
                reason="required path-segment evidence is incomplete",
                required_segments=path.segments,
            )
        return FabricVerificationResult(
            path_id=path.path_id,
            state=FabricPathState.VERIFIED,
            required_segments=path.segments,
        )

    @staticmethod
    def measure(
        verification: FabricVerificationResult,
        *,
        measurement: Mapping[str, object],
        observed_at: float | None = None,
    ) -> FabricVerificationResult:
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
                degraded = PhysicalFabricVerification.degrade(
                    verification,
                    reason=reason,
                    failure_domain=failure_domain,
                )
                return FabricVerificationResult(
                    path_id=degraded.path_id,
                    state=degraded.state,
                    reason=degraded.reason,
                    failure_domain=degraded.failure_domain,
                    history=degraded.history,
                    measurement=dict(measurement),
                    measurement_observed_at=(
                        observed_at
                        if observed_at is not None
                        else verification.measurement_observed_at
                    ),
                    required_segments=degraded.required_segments,
                )

        history = verification.history
        if verification.state is FabricPathState.REVERIFIED:
            history = history + (
                {
                    "state": verification.state.value,
                    "reason": "fresh post-recovery measurement",
                    "failure_domain": verification.failure_domain,
                    "prior_measurement": dict(verification.measurement),
                },
            )
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.MEASURED,
            history=history,
            measurement=dict(measurement),
            measurement_observed_at=observed_at if observed_at is not None else verification.measurement_observed_at,
            required_segments=verification.required_segments,
        )

    @staticmethod
    def degrade(
        verification: FabricVerificationResult,
        *,
        reason: str,
        failure_domain: str,
    ) -> FabricVerificationResult:
        history = verification.history + (
            {
                "state": verification.state.value,
                "reason": reason,
                "failure_domain": failure_domain,
            },
        )
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.DEGRADED,
            reason=reason,
            failure_domain=failure_domain,
            history=history,
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )

    @staticmethod
    def recover(verification: FabricVerificationResult) -> FabricVerificationResult:
        history = verification.history + (
            {
                "state": verification.state.value,
                "reason": verification.reason,
                "failure_domain": verification.failure_domain,
            },
        )
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.RECOVERED,
            history=history,
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )

    @staticmethod
    def fail(
        verification: FabricVerificationResult,
        *,
        reason: str,
        failure_domain: str,
    ) -> FabricVerificationResult:
        history = verification.history + (
            {
                "state": verification.state.value,
                "reason": reason,
                "failure_domain": failure_domain,
                "measurement": dict(verification.measurement),
            },
        )
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.FAILED,
            reason=reason,
            failure_domain=failure_domain,
            history=history,
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )

    @staticmethod
    def reverify(
        verification: FabricVerificationResult,
        *,
        evidence: Sequence[Mapping[str, object]],
    ) -> FabricVerificationResult:
        covered = {
            str(item.get("segment"))
            for item in evidence
            if str(item.get("result") or "").lower() == "pass"
            and item.get("segment")
        }
        required = set(verification.required_segments)
        complete = bool(required) and required.issubset(covered)
        return FabricVerificationResult(
            path_id=verification.path_id,
            state=FabricPathState.REVERIFIED if complete else verification.state,
            reason=None if complete else "fresh path-segment evidence is incomplete",
            history=verification.history + (
                {
                    "state": verification.state.value,
                    "reason": verification.reason,
                    "fresh_evidence_segments": sorted(covered),
                },
            ),
            measurement=dict(verification.measurement),
            required_segments=verification.required_segments,
        )


class AdaptiveFabricRouteSelector:
    """Select and reselect physical routes from current, path-specific evidence."""

    _ELIGIBLE_STATES = frozenset({
        FabricPathState.VERIFIED.value,
        FabricPathState.MEASURED.value,
        FabricPathState.REVERIFIED.value,
    })

    @classmethod
    def _candidates(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for raw in paths:
            path_id = str(raw.get("path_id") or "").strip()
            state = str(raw.get("state") or "").strip()
            if not path_id or state not in cls._ELIGIBLE_STATES:
                continue
            health = route_health.get(path_id)
            if not isinstance(health, Mapping):
                continue
            if state != FabricPathState.MEASURED.value:
                continue
            measurement = raw.get("measurement")
            if not isinstance(measurement, Mapping):
                continue
            candidates.append({
                "path_id": path_id,
                "health": dict(health),
                "measurement": dict(measurement),
                "state": state,
            })
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
    def select(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        candidates = sorted(cls._candidates(paths, route_health), key=cls._key)
        if not candidates:
            return {
                "path_id": None,
                "selection_reason": "no_current_measured_route",
                "alternatives": (),
                "evidence": (),
            }
        selected = candidates[0]
        return {
            "path_id": selected["path_id"],
            "selection_reason": "observed_route_health",
            "alternatives": tuple(str(item["path_id"]) for item in candidates[1:]),
            "evidence": tuple(
                {
                    "path_id": str(item["path_id"]),
                    "health": dict(item["health"]),
                    "measurement": dict(item["measurement"]),
                }
                for item in candidates
            ),
        }

    @classmethod
    def migration(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
        *,
        current_path_id: str,
    ) -> dict[str, object]:
        selection = cls.select(paths, route_health)
        selected = selection["path_id"]
        if selected is None:
            return {
                "migrate": False,
                "from_path_id": current_path_id,
                "to_path_id": None,
                "reason": "no_verified_alternative",
            }
        if str(selected) == str(current_path_id):
            return {
                "migrate": False,
                "from_path_id": current_path_id,
                "to_path_id": current_path_id,
                "reason": "current_route_remains_selected",
            }
        return {
            "migrate": True,
            "from_path_id": current_path_id,
            "to_path_id": str(selected),
            "reason": str(selection["selection_reason"]),
        }
