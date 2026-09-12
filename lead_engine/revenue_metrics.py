"""Production revenue-stage metrics and orphan detection."""
from __future__ import annotations

from typing import Any, Dict

from .agent_queue import pending


def collect_revenue_metrics(db: Any) -> Dict[str, int]:
    leads = db.all_leads()
    queue = pending(db)
    revenue_state = db.get_state("revenue_execution") or {}
    actions = revenue_state.get("actions", {}) if isinstance(revenue_state, dict) else {}
    outreach_actions = [item for item in actions.values() if isinstance(item, dict)]

    queued_sales = sum(1 for task in queue if task.get("agent") == "outreach_closer" and task.get("status") in {"queued", "running"})
    active_lifecycle = {"sales_active", "outreach_sent", "conversation_active", "awaiting_response"}
    terminal = {"closed_lost", "disqualified", "stopped", "converted", "referred"}
    orphaned = 0
    for lead in leads:
        if lead.get("qualified") is not True:
            continue
        lifecycle = str(lead.get("revenue_lifecycle_state") or "").strip().lower()
        has_sales_queue = lead.get("sales_eligibility") == "eligible" and any(
            task.get("agent") == "outreach_closer"
            and task.get("payload", {}).get("lead", {}).get("fingerprint") == lead.get("fingerprint")
            and task.get("status") in {"queued", "running"}
            for task in queue
        )
        has_conversation = bool(lead.get("conversation_id")) or lifecycle in active_lifecycle
        has_terminal_reason = lifecycle in terminal or bool(lead.get("sales_eligibility_reason") and lead.get("sales_eligibility") == "blocked")
        if not has_sales_queue and not has_conversation and not has_terminal_reason:
            orphaned += 1

    followups = sum(1 for lead in leads for item in (lead.get("outreach_history") or []) if isinstance(item, dict) and item.get("kind") == "follow_up")
    switches = sum(len(lead.get("route_switch_history") or []) for lead in leads if isinstance(lead.get("route_switch_history"), list))
    return {
        "discovered": len(leads),
        "researched": sum(1 for lead in leads if str(lead.get("research_status") or "").lower() == "complete"),
        "qualified": sum(1 for lead in leads if lead.get("qualified") is True),
        "sales_eligible": sum(1 for lead in leads if lead.get("sales_eligibility") == "eligible"),
        "sales_queued": queued_sales,
        "sales_active": sum(1 for lead in leads if str(lead.get("revenue_lifecycle_state") or "").lower() in active_lifecycle),
        "outreach_sent": sum(1 for action in outreach_actions if action.get("status") == "sent"),
        "responses_received": sum(int(lead.get("response_count", 0) or 0) for lead in leads),
        "conversations_active": sum(1 for lead in leads if str(lead.get("revenue_lifecycle_state") or "").lower() == "conversation_active"),
        "followups_executed": followups,
        "route_switches": switches,
        "converted": sum(1 for lead in leads if str(lead.get("revenue_lifecycle_state") or "").lower() == "converted" or str(lead.get("outreach_state") or "").lower() == "converted"),
        "referred": sum(1 for lead in leads if str(lead.get("revenue_lifecycle_state") or "").lower() == "referred"),
        "closed_lost": sum(1 for lead in leads if str(lead.get("revenue_lifecycle_state") or "").lower() == "closed_lost"),
        "disqualified": sum(1 for lead in leads if str(lead.get("revenue_lifecycle_state") or "").lower() == "disqualified"),
        "orphaned_qualified": orphaned,
    }
