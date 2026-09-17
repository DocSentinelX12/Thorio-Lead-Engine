from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_queue import pending
from .research_package import research_readiness


class ProductionResearchGateError(RuntimeError):
    """Raised when production contains an incomplete research or closer handoff."""


def validate_production_research_gate(db: Any) -> Dict[str, Any]:
    """Fail closed on research marked complete or sales-ready without a ready closer package."""
    leads = [item for item in db.all_leads() if isinstance(item, Mapping)]
    closer_tasks = pending(db, "outreach_closer")
    queued_by_fingerprint: Dict[str, list[Mapping[str, Any]]] = {}
    for task in closer_tasks:
        payload = task.get("payload") if isinstance(task, Mapping) else None
        lead = payload.get("lead") if isinstance(payload, Mapping) else None
        if isinstance(lead, Mapping):
            fingerprint = str(lead.get("fingerprint") or "").strip()
            if fingerprint:
                queued_by_fingerprint.setdefault(fingerprint, []).append(task)

    complete_checked = 0
    sales_checked = 0
    violations: list[Dict[str, Any]] = []

    for lead in leads:
        fingerprint = str(lead.get("fingerprint") or "").strip()
        if not fingerprint:
            continue
        research_status = str(lead.get("research_status") or "").strip().lower()
        sales_eligible = str(lead.get("sales_eligibility") or "").strip().lower() == "eligible"
        if research_status not in {"complete", "research_complete"} and not sales_eligible:
            continue

        readiness = research_readiness(lead)
        if research_status in {"complete", "research_complete"}:
            complete_checked += 1
            if not readiness["ready"]:
                violations.append({
                    "fingerprint": fingerprint,
                    "reason": "research_marked_complete_but_closer_not_ready",
                    "blockers": list(readiness["blockers"]),
                })

        if sales_eligible:
            sales_checked += 1
            if not readiness["ready"]:
                violations.append({
                    "fingerprint": fingerprint,
                    "reason": "sales_eligible_but_research_or_closer_not_ready",
                    "blockers": list(readiness["blockers"]),
                })
                continue

            sync_state = db.get_sync_state(fingerprint)
            if not sync_state.get("synced") or sync_state.get("last_error"):
                violations.append({
                    "fingerprint": fingerprint,
                    "reason": "sales_eligible_research_not_synced",
                    "sync_state": {
                        "synced": bool(sync_state.get("synced")),
                        "last_error": str(sync_state.get("last_error") or ""),
                    },
                })

            active = bool(lead.get("last_outreach_action_id")) or str(lead.get("outreach_state") or "").strip().lower() == "awaiting_response"
            if not active and not queued_by_fingerprint.get(fingerprint):
                violations.append({
                    "fingerprint": fingerprint,
                    "reason": "sales_eligible_missing_closer_task",
                })

    result = {
        "status": "verified" if not violations else "failed",
        "leads_checked": len(leads),
        "research_complete_checked": complete_checked,
        "sales_eligible_checked": sales_checked,
        "closer_tasks_pending": len(closer_tasks),
        "violations": violations,
    }
    if violations:
        raise ProductionResearchGateError(
            "RESEARCH/CLOSER GATE FAILURE: "
            + str(violations[:20])
            + (" ..." if len(violations) > 20 else "")
        )
    return result
