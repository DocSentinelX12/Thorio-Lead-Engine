"""Durable bridge between local LeadDB records and the GPU compute fabric."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from .compute_worker import ComputeWorkerClient, ComputeWorkerError


def _task_id(fingerprint: str) -> str:
    return f"lead-prepare:{fingerprint}"


def dispatch_pending_lead_compute(db: Any, client: ComputeWorkerClient, *, limit: int = 50) -> Dict[str, Any]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    dispatched = []
    retried = []
    for item in db.compute_lead_pending(limit):
        fingerprint = str(item["fingerprint"])
        task_id = _task_id(fingerprint)
        payload = {
            "kind": "lead_prepare",
            "leads": [dict(item["lead"])],
            "minimum_score": 0,
            "checkpoint_batch_size": 1,
        }
        try:
            client.enqueue(payload, task_id=task_id)
            db.compute_lead_mark_dispatched(fingerprint, task_id)
            dispatched.append(fingerprint)
        except Exception as error:
            db.compute_lead_mark_retry(fingerprint, str(error))
            retried.append({"fingerprint": fingerprint, "error": str(error)})
    return {"dispatched_count": len(dispatched), "retry_count": len(retried), "dispatched": dispatched, "retried": retried}


def reconcile_lead_compute(db: Any, client: ComputeWorkerClient, *, limit: int = 50) -> Dict[str, Any]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    completed = []
    retried = []
    for item in db.compute_lead_dispatched(limit):
        fingerprint = str(item["fingerprint"])
        task_id = str(item["task_id"])
        remote = client.status(task_id)
        status = str(remote.get("status") or "")
        if status in {"queued", "leased", "running"}:
            continue
        if status == "completed":
            result = remote.get("result")
            if not isinstance(result, Mapping):
                result = client.checkpoint_results(task_id)
            if not isinstance(result, Mapping):
                raise ComputeWorkerError(f"lead compute task {task_id} completed without durable result")
            leads = result.get("leads", [])
            if not isinstance(leads, list):
                leads = []
            matched = [lead for lead in leads if isinstance(lead, dict) and str(lead.get("fingerprint") or "").strip() == fingerprint]
            if len(matched) > 1:
                raise ComputeWorkerError(f"lead compute task {task_id} returned duplicate fingerprint {fingerprint}")
            if matched:
                stored = db.update_payload(fingerprint, matched[0])
                if stored is None:
                    raise ComputeWorkerError(f"lead disappeared before compute result persistence: {fingerprint}")
            db.compute_lead_mark_completed(fingerprint, {"remote_task_id": task_id, "result": dict(result), "matched": bool(matched)})
            completed.append(fingerprint)
            continue
        if status == "failed":
            error = str(remote.get("error") or f"remote lead compute failed: {task_id}")
            db.compute_lead_mark_retry(fingerprint, error)
            retried.append({"fingerprint": fingerprint, "error": error})
            continue
        raise ComputeWorkerError(f"unexpected lead compute state {status!r} for {task_id}")
    return {"completed_count": len(completed), "retried_count": len(retried), "completed": completed, "retried": retried}


def lead_compute_once(db: Any, client: ComputeWorkerClient, *, dispatch_limit: int = 50, reconcile_limit: int = 50) -> Dict[str, Any]:
    reconciled = reconcile_lead_compute(db, client, limit=reconcile_limit)
    dispatched = dispatch_pending_lead_compute(db, client, limit=dispatch_limit)
    return {
        "status": "ok",
        "completed_count": reconciled["completed_count"],
        "retried_count": reconciled["retried_count"],
        "dispatched_count": dispatched["dispatched_count"],
        "reconciled": reconciled,
        "dispatched": dispatched,
    }
