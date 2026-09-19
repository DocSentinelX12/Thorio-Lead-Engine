from __future__ import annotations

import os
import time
from typing import Any, Dict


def install() -> None:
    """Make the configured Airtable batch size a batch size, not a cycle cap."""
    from . import batch_delivery

    original = batch_delivery.sync_pending_batched
    if getattr(original, "_durable_drain_override", False):
        return

    def sync_pending_batched(db: Any, limit: int = 50) -> Dict[str, Any]:
        try:
            budget_seconds = float(os.environ.get("THORIO_AIRTABLE_DRAIN_SECONDS", "120").strip())
        except ValueError:
            budget_seconds = 120.0
        budget_seconds = max(1.0, budget_seconds)
        batch_limit = max(1, int(limit))
        started = time.monotonic()

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
            result = original(db, limit=batch_limit)
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
            if time.monotonic() - started >= budget_seconds:
                break

        aggregate["elapsed_seconds"] = round(time.monotonic() - started, 3)
        aggregate["drain_budget_seconds"] = budget_seconds
        return aggregate

    sync_pending_batched._durable_drain_override = True
    batch_delivery.sync_pending_batched = sync_pending_batched
