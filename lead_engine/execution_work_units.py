"""Deterministic partitioning for independent GPU work units.

This is deliberately narrower than model-parallel execution. It creates durable,
independent units that can be assigned to separate physical GPUs without
requiring inter-worker synchronization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .execution_fabric_contract import ExecutionMode


_INDEPENDENT_MODES = frozenset(
    {
        ExecutionMode.BATCH_PARALLEL,
        ExecutionMode.DATA_PARALLEL,
    }
)


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
            raise ValueError("work unit mode must be an independent execution mode")


def build_independent_work_units(
    *,
    workload_id: str,
    items: Iterable[Any],
    mode: ExecutionMode,
) -> tuple[WorkUnit, ...]:
    workload_id = str(workload_id).strip()
    if not workload_id:
        raise ValueError("workload_id is required")
    if mode not in _INDEPENDENT_MODES:
        raise ValueError(
            f"{mode.value} is not an independent work-unit execution mode"
        )

    materialized = tuple(items)
    if not materialized:
        raise ValueError("at least one item is required")

    return tuple(
        WorkUnit(
            unit_id=f"{workload_id}:{index}",
            workload_id=workload_id,
            item_index=index,
            item=item,
            mode=mode,
        )
        for index, item in enumerate(materialized)
    )
