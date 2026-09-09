from __future__ import annotations

from typing import Any, Dict

from .qualification import apply_company_qualification
from .research_queue import queue_paxus_research
from .sync_worker import sync_one


QUALIFICATION_STATES = {
    "qualified",
    "in_review",
    "unverified",
}


def apply_discovery_gate(pipeline, result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply company qualification and Paxus research routing to a discovery result.

    Discovery is deliberately additive: it never deletes an opportunity because
    a qualification gate is unknown. Qualified companies remain independently
    represented in qualification_results and Paxus research is queued only for
    Paxus-qualified opportunities that are not yet true referrals.
    """
    if not isinstance(result, dict):
        raise ValueError("result must be a dictionary")

    fingerprint = str(result.get("fingerprint") or "").strip()
    if not fingerprint:
        return result

    lead = pipeline.db.get(fingerprint)
    if lead is None:
        return result

    evaluated = apply_company_qualification(dict(lead))
    stored = pipeline.db.update_payload(fingerprint, evaluated)
    if stored is None:
        raise ValueError(f"Unable to apply discovery qualification: {fingerprint}")

    paxus = (stored.get("qualification_results") or {}).get("Paxus", {})
    paxus_queue = queue_paxus_research(pipeline.db, stored)
    stored = pipeline.db.get(fingerprint) or stored

    sync_status = None
    sync_error = None
    if pipeline.sync_enabled:
        sync_result = sync_one(stored)
        sync_status = sync_result.get("status", "failed")
        sync_error = sync_result.get("error")
        if sync_status in {"synced", "already_exists"}:
            pipeline.db.mark_synced(fingerprint)
        else:
            pipeline.db.mark_error(
                fingerprint,
                sync_error or "Discovery qualification synchronization failed.",
            )

    updated = dict(result)
    updated["lead"] = stored
    updated["potential_routes"] = stored.get("potential_routes", [])
    updated["qualification_results"] = stored.get("qualification_results", {})
    updated["qualification_status"] = stored.get("qualification_status", "unverified")
    updated["review_state"] = stored.get("review_state", "awaiting_review")
    updated["research_status"] = stored.get("research_status", "complete")
    updated["paxus_qualified"] = bool(paxus.get("qualified"))
    updated["paxus_true_referral"] = bool(paxus.get("true_referral"))
    updated["paxus_research_status"] = paxus_queue.get("status")
    updated["sync_status"] = sync_status or updated.get("sync_status")
    updated["sync_error"] = sync_error
    return updated
