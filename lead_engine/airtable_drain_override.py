from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict


def install() -> None:
    """Keep the existing batch-delivery function unchanged.

    Durable draining is an orchestration concern, not a change to the
    one-batch sync contract. Production callers use drain_pending().
    """
    return None


def drain_pending(
    db: Any,
    limit: int = 50,
    sync_batch: Callable[..., Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Durably drain pending Airtable work through repeated real batches.

    The underlying sync_pending_batched() call remains exactly one batch.
    This function owns repetition, bounded runtime, failure stopping, and
    durable backlog preservation for continuous production operation.
    """
    if sync_batch is None:
        from . import batch_delivery
        sync_batch = batch_delivery.sync_pending_batched

    try:
        budget_seconds = float(os.environ.get("THORIO_AIRTABLE_DRAIN_SECONDS", "120").strip())
    except ValueError:
        budget_seconds = 120.0
    budget_seconds = max(1.0, budget_seconds)
    batch_limit = max(1, int(limit))
    started = time.perf_counter()

    aggregate: Dict[str, Any] = {
        "synced": [],
        "already_exists": [],
        "failed": [],
        "synced_count": 0,
        "already_exists_count": 0,
        "failed_count": 0,
        "batches": 0,
        "drain_complete": False,
    }

    while True:
        result = sync_batch(db, limit=batch_limit)
        if not isinstance(result, dict):
            raise RuntimeError("Airtable sync returned a non-object result")

        for key in ("synced", "already_exists", "failed"):
            values = result.get(key)
            if isinstance(values, list):
                aggregate[key].extend(values)

        aggregate["synced_count"] += int(result.get("synced_count", 0) or 0)
        aggregate["already_exists_count"] += int(result.get("already_exists_count", 0) or 0)
        aggregate["failed_count"] += int(result.get("failed_count", 0) or 0)
        aggregate["batches"] += 1

        processed = (
            int(result.get("synced_count", 0) or 0)
            + int(result.get("already_exists_count", 0) or 0)
            + int(result.get("failed_count", 0) or 0)
        )
        if int(result.get("failed_count", 0) or 0) > 0:
            break
        if processed < batch_limit:
            aggregate["drain_complete"] = True
            break
        if time.perf_counter() - started >= budget_seconds:
            break

    aggregate["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    aggregate["drain_budget_seconds"] = budget_seconds
    return aggregate
