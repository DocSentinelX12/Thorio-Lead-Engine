"""Physical resource scheduler for the additive Thorio compute fabric.

This module schedules execution resources only. It never owns lead, Airtable,
qualification, outreach, revenue, or Partnership state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .compute_inventory import ComputeInventory
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

    def __init__(self, inventory: ComputeInventory):
        self.inventory = inventory

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
    def _rank_gpus_for_placement(cls, gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
        topology_counts: dict[str, int] = {}
        numa_counts: dict[tuple[str, Any], int] = {}
        for gpu in gpus:
            payload = json.loads(gpu["payload_json"])
            topology_key = cls._topology_group_key(gpu)
            topology_counts[topology_key] = topology_counts.get(topology_key, 0) + 1
            numa_key = (topology_key, payload.get("numa_node"))
            numa_counts[numa_key] = numa_counts.get(numa_key, 0) + 1

        def rank(gpu: dict[str, Any]) -> tuple[int, int, str, str]:
            payload = json.loads(gpu["payload_json"])
            topology_key = cls._topology_group_key(gpu)
            numa_key = (topology_key, payload.get("numa_node"))
            return (
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

    def _candidates(self, requirements: ComputeRequirements) -> list[dict[str, Any]]:
        rows = self.inventory.eligible()
        grouped = self._node_from_rows(rows)
        candidates = []
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
            if requirements.topology_domain is not None:
                compatible = [
                    gpu for gpu in compatible
                    if json.loads(gpu["payload_json"]).get("topology_domain") == requirements.topology_domain
                ]
            if requirements.gpu.require_nccl:
                nccl = node_payload.get("nccl_version")
                if not nccl:
                    continue
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
                "gpus": self._rank_gpus_for_placement(compatible),
                "payload": node_payload,
            })
        return candidates

    def allocate(self, requirements: ComputeRequirements, allocation_id: str) -> ComputeAllocation:
        if not allocation_id.strip():
            raise ValueError("allocation_id is required")
        candidates = self._candidates(requirements)
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
                group_selected: list[dict[str, Any]] = []
                total = 0
                ranked_group = sorted(
                    group,
                    key=lambda candidate: (
                        -self._node_topology_score(candidate)[0],
                        -self._node_topology_score(candidate)[1],
                        -self._node_topology_score(candidate)[2],
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
                    str(candidate["node_id"]),
                ),
            )
            for candidate in ranked_candidates:
                if len(candidate["gpus"]) >= needed:
                    selected = [candidate]
                    break
            if not selected:
                raise ComputeSchedulingError("no compatible allocation")

        resources = [candidate["cpu"] for candidate in selected]
        gpu_rows: list[dict[str, Any]] = []
        remaining = needed
        if requirements.workload_class == WorkloadClass.MULTI_NODE_GPU:
            # Every selected node contributes one GPU first. Remaining GPUs are
            # then packed deterministically without ever removing a node.
            if needed < len(selected):
                raise ComputeSchedulingError("multi-node allocation needs at least one GPU per selected node")
            for candidate in selected:
                ranked = self._rank_gpus_for_placement(candidate["gpus"])
                gpu_rows.append(ranked[0])
                remaining -= 1
            for candidate in selected:
                if remaining <= 0:
                    break
                ranked = self._rank_gpus_for_placement(candidate["gpus"])
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
            capability_evidence=tuple(
                json.loads(row["payload_json"]) | {"resource_key": row["resource_key"]}
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
