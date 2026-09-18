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
            if requirements.gpu.gpu_count > len(compatible):
                continue
            candidates.append({
                "node_id": node_id,
                "cpu": cpu,
                "gpus": compatible,
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
            for candidate in candidates:
                if candidate["gpus"]:
                    selected.append(candidate)
                    total = sum(len(c["gpus"]) for c in selected)
                    if len(selected) >= 2 and total >= needed:
                        break
            if len(selected) < 2 or sum(len(c["gpus"]) for c in selected) < needed:
                raise ComputeSchedulingError("no compatible multi-node allocation")
        else:
            for candidate in candidates:
                if len(candidate["gpus"]) >= needed:
                    selected = [candidate]
                    break
            if not selected:
                raise ComputeSchedulingError("no compatible allocation")

        resources = [candidate["cpu"] for candidate in selected]
        gpu_rows: list[dict[str, Any]] = []
        remaining = needed
        for candidate in selected:
            take = min(remaining, len(candidate["gpus"]))
            gpu_rows.extend(candidate["gpus"][:take])
            remaining -= take
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
