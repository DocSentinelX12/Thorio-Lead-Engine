from __future__ import annotations

from typing import Any, Dict

from .qualification import apply_company_qualification
from .research_queue import queue_paxus_research


def apply_discovery_gate(
    pipeline,
    result: Dict[str, Any],
    *,
    qualify: bool = False,
) -> Dict[str, Any]:
    """Apply the discovery boundary with explicit qualification control.

    Discovery is evidence collection only. Qualification A is the first
    specialist permitted to make a qualification decision. The explicit
    ``qualify=True`` compatibility mode preserves the legacy direct-call
    behavior for callers that intentionally invoke the old gate semantics.
    """
    if not isinstance(result, dict):
        raise ValueError("result must be a dictionary")

    fingerprint = str(result.get("fingerprint") or "").strip()
    if not fingerprint:
        return result

    lead = pipeline.db.get(fingerprint)
    if lead is None:
        return result

    if not qualify:
        updated = dict(result)
        updated["lead"] = lead
        updated["qualification_performed"] = False
        updated["handoff"] = "qualification_a"
        return updated

    evaluated = apply_company_qualification(dict(lead))
    stored = pipeline.db.update_payload(fingerprint, evaluated)
    if stored is None:
        raise ValueError(f"Unable to apply discovery qualification: {fingerprint}")

    paxus = (stored.get("qualification_results") or {}).get("Paxus", {})
    paxus_queue = queue_paxus_research(pipeline.db, stored)
    stored = pipeline.db.get(fingerprint) or stored

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
    # Do not call sync_one here. pipeline.process() already synchronized this
    # discovery record, and repeating it turns one transient failure into two
    # recorded attempts and can corrupt retry accounting.
    return updated
