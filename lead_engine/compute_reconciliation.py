"""Reconcile physical compute allocations against durable execution attempts.

The Thorio business queue remains authoritative. This module only repairs the
execution/resource boundary and never marks business work complete.
"""
from __future__ import annotations

from typing import Any


TERMINAL_ATTEMPT_STATES = frozenset({"completed", "released", "expired"})


def reconcile_allocations(
    inventory: Any,
    coordinator: Any,
    *,
    reservation_ttl_seconds: float | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Reconcile durable physical allocations with execution-attempt state.

    Bound allocations whose exact execution attempt is terminal are released.
    Expired coordinator leases are recovered before allocation inspection.
    Unbound reservations are retained unless an explicit TTL is supplied.

    No business-work state is changed here.
    """
    if reservation_ttl_seconds is not None and reservation_ttl_seconds < 0:
        raise ValueError("reservation_ttl_seconds must be non-negative")
    recovered = int(coordinator.recover_expired_tasks())
    current = __import__("time").time() if now is None else float(now)

    released = []
    unbound = []
    active = []
    stale_workers = []
    anomalies = []

    for allocation in inventory.allocations():
        if allocation["state"] not in {"reserved", "bound"}:
            continue

        allocation_id = allocation["allocation_id"]
        if allocation["state"] == "reserved" and not allocation.get("attempt_id"):
            age = max(0.0, current - float(allocation["updated_at"]))
            if reservation_ttl_seconds is not None and age >= reservation_ttl_seconds:
                count = inventory.release_allocation(
                    allocation_id,
                    reason="unbound allocation reservation expired",
                )
                if count:
                    released.append(allocation_id)
                    continue
            unbound.append(allocation_id)
            continue

        task_id = allocation.get("task_id")
        attempt_id = allocation.get("attempt_id")
        generation = allocation.get("generation")
        if not task_id or not attempt_id or generation is None:
            anomalies.append({
                "allocation_id": allocation_id,
                "reason": "bound allocation is missing execution identity",
            })
            continue

        attempt = coordinator.execution_attempt(attempt_id)
        if attempt is None or attempt["task_id"] != task_id or int(attempt["generation"]) != int(generation):
            count = inventory.release_allocation(
                allocation_id,
                task_id=task_id,
                attempt_id=attempt_id,
                generation=int(generation),
                reason="execution attempt missing or mismatched",
            )
            if count:
                released.append(allocation_id)
            else:
                anomalies.append({
                    "allocation_id": allocation_id,
                    "reason": "execution attempt missing or mismatched and allocation release was rejected",
                })
            continue

        if attempt["status"] in TERMINAL_ATTEMPT_STATES:
            count = inventory.release_allocation(
                allocation_id,
                task_id=task_id,
                attempt_id=attempt_id,
                generation=int(generation),
                reason=f"execution attempt {attempt['status']}",
            )
            if count:
                released.append(allocation_id)
            else:
                anomalies.append({
                    "allocation_id": allocation_id,
                    "reason": "terminal attempt allocation release was rejected",
                })
            continue

        if attempt["status"] == "leased":
            worker = coordinator.pool.worker(attempt["worker_id"])
            if worker and worker["status"] == "stale":
                stale_workers.append(allocation_id)
            active.append(allocation_id)
            continue

        anomalies.append({
            "allocation_id": allocation_id,
            "reason": f"unexpected execution attempt state {attempt['status']!r}",
        })

    return {
        "status": "ok" if not anomalies else "anomalies",
        "expired_recovered_count": recovered,
        "released_count": len(released),
        "released": released,
        "active_count": len(active),
        "active": active,
        "unbound_count": len(unbound),
        "unbound": unbound,
        "stale_worker_count": len(stale_workers),
        "stale_workers": stale_workers,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
