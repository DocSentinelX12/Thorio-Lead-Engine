"""Durable autonomous sales conversation state and inbound event handling."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from .agent_queue import enqueue
from .outreach_engine import STOP_STATES, objection_response

STATE_KEY = "revenue_conversations"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load(db) -> Dict[str, Any]:
    state = db.get_state(STATE_KEY)
    if not isinstance(state, dict): return {"conversations": {}}
    conversations = state.get("conversations")
    return {"conversations": conversations if isinstance(conversations, dict) else {}}

def _save(db, state: Dict[str, Any]) -> None:
    db.set_state(STATE_KEY, state)

def _conversation_key(opportunity_id: str, conversation_id: str) -> str:
    return f"{str(opportunity_id).strip()}::{str(conversation_id).strip()}"

def _classify(text: str) -> str:
    value = str(text or "").strip().lower()
    if any(token in value for token in ("unsubscribe", "remove me", "stop", "do not contact", "don't contact", "not interested", "no thanks")): return "opted_out"
    if any(token in value for token in ("signed the contract", "contract is signed", "contract has been signed", "we signed", "we've signed", "we have signed", "hired you", "we hired", "we've hired", "we have hired", "payment sent", "payment received", "paid the invoice", "invoice paid", "deal closed", "closed the deal")): return "converted"
    if any(token in value for token in ("yes", "interested", "tell me more", "sounds good", "let's talk", "lets talk", "book", "schedule")): return "interested"
    if any(token in value for token in ("price", "pricing", "cost", "too expensive")): return "objection"
    if any(token in value for token in ("later", "next month", "not now", "timing")): return "objection"
    return "replied"

def _route_switch(
    lead: Mapping[str, Any],
    suggested_route: Optional[str],
    text: str,
) -> tuple[str | None, str | None, str | None]:
    candidate = str(suggested_route or "").strip()
    if not candidate:
        return None, None, None
    allowed = {
        str(item).strip()
        for item in (
            lead.get("preserved_routes")
            or lead.get("eligible_routes")
            or lead.get("potential_routes")
            or []
        )
    }
    if candidate not in allowed:
        return None, "suggested_route_not_preserved", None

    qualification_results = lead.get("qualification_results")
    route_result = (
        qualification_results.get(candidate)
        if isinstance(qualification_results, Mapping)
        else None
    )
    if not isinstance(route_result, Mapping) or route_result.get("qualified") is not True:
        return None, "route_switch_candidate_not_qualified", None
    route_research = route_result.get("route_research")
    if not isinstance(route_research, Mapping) or route_research.get("verified") is not True:
        return None, "route_switch_candidate_research_not_verified", None
    if candidate == "Paxus" and route_result.get("true_referral") is not True:
        return None, "route_switch_paxus_true_referral_not_verified", None
    if candidate == "Astrivon Labs" and route_result.get("service_fit_verified") is not True:
        return None, "route_switch_astrivon_service_fit_not_verified", None

    value = str(text or "").strip().lower()
    route_terms = {
        "Thorio": (
            "remote",
            "remote hiring",
            "remote engineer",
            "remote developer",
            "remote software",
            "remote tech",
            "remote team",
        ),
        "Shiftr": (
            "build",
            "software",
            "saas",
            "ai",
            "automation",
            "llm",
            "engineering team",
            "development team",
            "dedicated team",
            "staff augmentation",
            "outsourcing",
        ),
        "Paxus": (
            "hire",
            "hiring",
            "recruit",
            "recruiting",
            "staffing",
            "talent",
            "developers",
            "engineers",
            "technology staffing",
            "technical hiring",
        ),

        "Astrivon Labs": (
            "dev agency", "tech partner", "mvp", "b2b outreach", "b2b sales", "lead generation",
            "sales automation", "ai/ml", "computer vision", "business workflow", "crm automation",
            "full-stack software engineer", "web/mobile app", "seed funding", "non-technical founder",
            "outsource sales pipeline", "reduce in-house dev costs", "reduce in-house sales costs",
        ),    }
    terms = route_terms.get(candidate, ())
    matched = next((term for term in terms if term in value), None)
    if matched is None:
        return None, "route_switch_evidence_not_verified", None

    current = str(lead.get("outreach_route") or "").strip()
    if current and current != candidate:
        evidence_text = str(text or "").strip()
        return candidate, f"conversation_evidence_switch:{current}->{candidate}", evidence_text
    return None, None, None

def record_inbound_event(db: Any, *, opportunity_id: str, conversation_id: str, event_id: str, text: str, outcome: Optional[str] = None, objection: Optional[str] = None, suggested_route: Optional[str] = None, commercial_evidence: Optional[str] = None) -> Dict[str, Any]:
    opportunity_id = str(opportunity_id or "").strip(); conversation_id = str(conversation_id or "").strip(); event_id = str(event_id or "").strip()
    if not opportunity_id or not conversation_id or not event_id: raise ValueError("opportunity_id, conversation_id, and event_id are required")
    lead = db.get(opportunity_id)
    if lead is None: raise ValueError(f"lead not found: {opportunity_id}")
    state = _load(db); key = _conversation_key(opportunity_id, conversation_id)
    conversation = state["conversations"].setdefault(key, {"opportunity_id": opportunity_id, "conversation_id": conversation_id, "events": [], "processed_event_ids": [], "created_at": _now()})
    if event_id in conversation["processed_event_ids"]: return dict(conversation)
    classified = str(outcome or _classify(text)).strip().lower()
    if classified == "referred":
        referral_submitted = lead.get("referral_submitted") is True or lead.get("shiftr_referral_submitted") is True
        if not referral_submitted:
            raise ValueError("referred outcome requires durable referral submission")
    if classified == "converted":
        commercial_evidence_value = str(commercial_evidence or text or "").strip()
        if not commercial_evidence_value:
            raise ValueError("converted outcome requires commercial evidence")
    else:
        commercial_evidence_value = str(commercial_evidence or "").strip()
    event = {"event_id": event_id, "direction": "inbound", "at": _now(), "text": str(text or ""), "outcome": classified}
    if objection: event["objection"] = str(objection)
    conversation["events"].append(event); conversation["processed_event_ids"].append(event_id); conversation["last_inbound_at"] = event["at"]; conversation["response_count"] = int(conversation.get("response_count", 0) or 0) + 1
    switched_route, switch_evidence, switch_evidence_text = _route_switch(lead, suggested_route, text)
    existing_route_history = list(lead.get("route_switch_history") or []) if isinstance(lead.get("route_switch_history"), list) else []
    updated = dict(lead); updated.update({"conversation_id": conversation_id, "conversation_events": list(conversation["events"]), "response_count": conversation["response_count"], "last_response_at": event["at"], "last_response_outcome": classified, "outreach_state": classified, "revenue_lifecycle_state": "conversation_active", "route_switch_history": existing_route_history})
    if switched_route:
        history = list(updated.get("route_switch_history") or []) if isinstance(updated.get("route_switch_history"), list) else []
        history.append({"at": event["at"], "from": updated.get("outreach_route"), "to": switched_route, "evidence": switch_evidence, "evidence_text": switch_evidence_text}); updated["route_switch_history"] = history; updated["outreach_route"] = switched_route; updated["active_route"] = switched_route
    if switch_evidence and not switched_route:
        event.setdefault("warnings", []).append(switch_evidence)
        conversation.setdefault("warnings", []).append(switch_evidence)
        conversation["events"][-1] = event
    if classified in {"converted", "referred"}:
        updated["revenue_lifecycle_state"] = classified
        updated["outreach_state"] = classified
        updated["outreach_stop_reason"] = classified
        updated["next_follow_up_at"] = None
        updated["follow_up_due"] = False
        updated["commercial_outcome"] = {
            "type": classified,
            "at": event["at"],
            "evidence": commercial_evidence_value or (
                "durable_referral_submission" if classified == "referred" else ""
            ),
            "route": str(updated.get("outreach_route") or "").strip(),
        }
    elif classified in STOP_STATES or classified == "opted_out":
        updated["revenue_lifecycle_state"] = "closed_lost"
        updated["outreach_stop_reason"] = classified
        updated["next_follow_up_at"] = None
        updated["follow_up_due"] = False
    elif classified in {"interested", "replied", "objection"}:
        updated["next_follow_up_at"] = _now(); updated["follow_up_due"] = True; updated["outreach_state"] = "awaiting_response"
        enqueue(db, "follow_up", {"lead": updated, "outcome": classified, "objection": objection or (text if classified == "objection" else ""), "conversation_id": conversation_id, "inbound_event_id": event_id, "execute": True}, priority=10, dedupe_key=f"conversation_followup:{opportunity_id}:{event_id}")
    stored = db.update_payload(opportunity_id, updated) or updated
    conversation["outreach_route"] = stored.get("outreach_route"); conversation["next_action"] = "stop" if classified in STOP_STATES or classified == "opted_out" else "closer_follow_up"; conversation["updated_at"] = _now(); _save(db, state)
    return dict(conversation)

def due_followups(db, *, now: Optional[datetime] = None, limit: int = 100) -> list[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc); due: list[Dict[str, Any]] = []
    for lead in db.all_leads():
        if len(due) >= limit or lead.get("follow_up_due") is not True or str(lead.get("outreach_state") or "").lower() in STOP_STATES: continue
        raw = str(lead.get("next_follow_up_at") or "").strip()
        if not raw: continue
        try: when = datetime.fromisoformat(raw.replace("Z", "+00:00")); when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except ValueError: continue
        if when <= now: due.append(dict(lead))
    return due

def enqueue_due_followups(db: Any, *, now: Optional[datetime] = None, limit: int = 100) -> int:
    from .browser_revenue_inbound import poll_browser_revenue_inbound
    inbound_result = poll_browser_revenue_inbound(db, limit=limit)
    if not isinstance(inbound_result, Mapping):
        raise RuntimeError("revenue inbound observer returned an invalid result")
    health = dict(inbound_result)
    health["status"] = "failed" if int(inbound_result.get("failed_count", 0) or 0) > 0 else str(inbound_result.get("status") or "completed")
    health["checked_at"] = _now()
    if hasattr(db, "set_state"):
        db.set_state("revenue_inbound_health", health)
    if int(inbound_result.get("failed_count", 0) or 0) > 0:
        return 0
    queued = 0
    for lead in due_followups(db, now=now, limit=limit):
        fingerprint = str(lead.get("fingerprint") or "").strip()
        if not fingerprint: continue
        due_at = str(lead.get("next_follow_up_at") or "").strip()
        enqueue(db, "follow_up", {"lead": lead, "outcome": "no_response", "execute": True}, priority=10, dedupe_key=f"scheduled_followup:{fingerprint}:{due_at}"); queued += 1
    return queued

def objection_reply(text: str, route: str) -> str:
    return objection_response(text, route)
