from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_queue import pending
from .research_package import research_readiness
from .research_intelligence import validate_research_intelligence


class ProductionResearchGateError(RuntimeError):
    """Raised when production contains incomplete research or closer handoff."""


def _validated_intelligence(lead: Mapping[str, Any]) -> tuple[bool, list[str]]:
    intelligence = lead.get("research_intelligence")
    if not isinstance(intelligence, Mapping) or not intelligence:
        return False, ["research_intelligence"]
    opportunity_id = str(lead.get("opportunity_id") or lead.get("fingerprint") or "").strip()
    if not opportunity_id:
        return False, ["opportunity_id"]
    try:
        validate_research_intelligence(intelligence, opportunity_id=opportunity_id)
    except ValueError:
        return False, ["research_intelligence"]
    graph = intelligence.get("evidence_graph")
    claims = intelligence.get("claims")
    if not isinstance(graph, Mapping) or not isinstance(graph.get("nodes"), Mapping) or not graph["nodes"]:
        return False, ["research_intelligence"]
    if not isinstance(claims, list) or not claims:
        return False, ["research_intelligence"]
    if not isinstance(intelligence.get("handoff"), Mapping) or intelligence["handoff"].get("ready") is not True:
        return False, ["research_intelligence"]
    return True, []


def validate_production_research_gate(db: Any) -> Dict[str, Any]:
    """Fail closed on any complete or sales-ready opportunity lacking complete intelligence and closer readiness."""
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
        intelligence_ready, intelligence_blockers = _validated_intelligence(lead)
        if research_status in {"complete", "research_complete"}:
            complete_checked += 1
            if not readiness["ready"] or not readiness["closer_package_ready"] or not intelligence_ready:
                blockers = list(readiness["blockers"])
                blockers.extend(item for item in intelligence_blockers if item not in blockers)
                if not readiness["closer_package_ready"] and "closer_package_not_ready" not in blockers:
                    blockers.append("closer_package_not_ready")
                violations.append({"fingerprint": fingerprint, "reason": "research_marked_complete_but_closer_not_ready", "blockers": blockers})

        if sales_eligible:
            sales_checked += 1
            if not readiness["ready"] or not readiness["closer_package_ready"] or not intelligence_ready:
                blockers = list(readiness["blockers"])
                blockers.extend(item for item in intelligence_blockers if item not in blockers)
                violations.append({"fingerprint": fingerprint, "reason": "sales_eligible_but_research_or_closer_not_ready", "blockers": blockers})
                continue

            sync_state = db.get_sync_state(fingerprint)
            if not sync_state.get("synced") or sync_state.get("last_error"):
                violations.append({"fingerprint": fingerprint, "reason": "sales_eligible_research_not_synced", "sync_state": {"synced": bool(sync_state.get("synced")), "last_error": str(sync_state.get("last_error") or "")}})

            active = bool(lead.get("last_outreach_action_id")) or str(lead.get("outreach_state") or "").strip().lower() == "awaiting_response"
            if not active and not queued_by_fingerprint.get(fingerprint):
                violations.append({"fingerprint": fingerprint, "reason": "sales_eligible_missing_closer_task"})

    result = {"status": "verified" if not violations else "failed", "leads_checked": len(leads), "research_complete_checked": complete_checked, "sales_eligible_checked": sales_checked, "closer_tasks_pending": len(closer_tasks), "violations": violations}
    if violations:
        raise ProductionResearchGateError("RESEARCH/CLOSER GATE FAILURE: " + str(violations[:20]) + (" ..." if len(violations) > 20 else ""))
    return result
