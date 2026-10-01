"""Deterministic partitioning for independent GPU work units."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .execution_fabric_contract import ExecutionMode

_INDEPENDENT_MODES = frozenset({
    ExecutionMode.SINGLE_GPU,
    ExecutionMode.BATCH_PARALLEL,
    ExecutionMode.DATA_PARALLEL,
})


@dataclass(frozen=True)
class WorkUnit:
    unit_id: str
    workload_id: str
    item_index: int
    item: Any
    mode: ExecutionMode

    def __post_init__(self) -> None:
        if not self.unit_id.strip() or not self.workload_id.strip():
            raise ValueError("unit_id and workload_id are required")
        if self.item_index < 0:
            raise ValueError("item_index must not be negative")
        if self.mode not in _INDEPENDENT_MODES:
            raise ValueError("work unit mode must be an independently executable GPU mode")


def build_independent_work_units(*, workload_id: str, items: Iterable[Any],
                                 mode: ExecutionMode) -> tuple[WorkUnit, ...]:
    workload_id = str(workload_id).strip()
    if not workload_id:
        raise ValueError("workload_id is required")
    if mode not in _INDEPENDENT_MODES:
        raise ValueError(f"{mode.value} is not an independent work-unit execution mode")
    materialized = tuple(items)
    if not materialized:
        raise ValueError("at least one item is required")
    return tuple(
        WorkUnit(f"{workload_id}:{index}", workload_id, index, item, mode)
        for index, item in enumerate(materialized)
    )


def build_gpu_workload_payload(unit: WorkUnit, *, command: Sequence[str],
                               timeout_seconds: float | None = None) -> dict[str, Any]:
    if not isinstance(unit, WorkUnit):
        raise TypeError("unit must be a WorkUnit")
    normalized_command = tuple(str(item).strip() for item in command)
    if not normalized_command or any(not item for item in normalized_command):
        raise ValueError("command must contain at least one non-empty argument")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    payload: dict[str, Any] = {
        "kind": "gpu_workload",
        "workload_id": unit.workload_id,
        "work_unit_id": unit.unit_id,
        "work_unit_index": unit.item_index,
        "work_unit_item": unit.item,
        "execution_mode": unit.mode.value,
        "compute_requirements": {
            "workload_class": "gpu_required",
            "gpu": {"gpu_count": 1},
            "same_node": True,
        },
        "command": list(normalized_command),
    }
    if timeout_seconds is not None:
        payload["timeout_seconds"] = float(timeout_seconds)
    return payload
