"""Durable autonomous sales conversation state and inbound event handling."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from .agent_queue import enqueue
from .outreach_engine import STOP_STATES, objection_response

STATE_KEY = "revenue_conversations"
CLOSER_ROLE = "high_ticket_sales_closer"

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
    if any(token in value for token in ("yes", "interested", "tell me more", "sounds good", "let's talk", "lets talk", "book", "schedule")): return "interested"
    if any(token in value for token in ("price", "pricing", "cost", "too expensive")): return "objection"
    if any(token in value for token in ("later", "next month", "not now", "timing")): return "objection"
    return "replied"

def _route_switch(lead: Mapping[str, Any], suggested_route: Optional[str]) -> tuple[str | None, str | None]:
    candidate = str(suggested_route or "").strip()
    if not candidate: return None, None
    allowed = {str(item).strip() for item in (lead.get("preserved_routes") or lead.get("eligible_routes") or lead.get("potential_routes") or [])}
    if candidate not in allowed: return None, "suggested_route_not_preserved"
    current = str(lead.get("outreach_route") or "").strip()
    if current and current != candidate: return candidate, f"conversation_evidence_switch:{current}->{candidate}"
    return None, None

def record_inbound_event(db: Any, *, opportunity_id: str, conversation_id: str, event_id: str, text: str, outcome: Optional[str] = None, objection: Optional[str] = None, suggested_route: Optional[str] = None) -> Dict[str, Any]:
    opportunity_id = str(opportunity_id or "").strip(); conversation_id = str(conversation_id or "").strip(); event_id = str(event_id or "").strip()
    if not opportunity_id or not conversation_id or not event_id: raise ValueError("opportunity_id, conversation_id, and event_id are required")
    lead = db.get(opportunity_id)
    if lead is None: raise ValueError(f"lead not found: {opportunity_id}")
    state = _load(db); key = _conversation_key(opportunity_id, conversation_id)
    conversation = state["conversations"].setdefault(key, {"opportunity_id": opportunity_id, "conversation_id": conversation_id, "events": [], "processed_event_ids": [], "created_at": _now()})
    durable_events = lead.get("conversation_events") if isinstance(lead.get("conversation_events"), list) else []
    durable_by_id = {
        str(item.get("event_id") or "").strip(): dict(item)
        for item in durable_events
        if isinstance(item, Mapping) and str(item.get("event_id") or "").strip()
    }
    controller_events = {
        str(item.get("event_id") or "").strip(): dict(item)
        for item in conversation.get("events", [])
        if isinstance(item, Mapping) and str(item.get("event_id") or "").strip()
    }
    if event_id in durable_by_id:
        conversation["events"] = list(durable_by_id.values())
        conversation["processed_event_ids"] = list(durable_by_id)
        conversation["response_count"] = max(
            int(conversation.get("response_count", 0) or 0),
            int(lead.get("response_count", 0) or 0),
            sum(
                1
                for item in conversation["events"]
                if str(item.get("direction") or "inbound").strip().lower() == "inbound"
            ),
        )
        inbound_events = [
            item for item in conversation["events"]
            if str(item.get("direction") or "inbound").strip().lower() == "inbound"
        ]
        if inbound_events:
            conversation["last_inbound_at"] = str(inbound_events[-1].get("at") or "").strip() or conversation.get("last_inbound_at")
        conversation["updated_at"] = _now()
        _save(db, state)
        return dict(conversation)
    if event_id in conversation["processed_event_ids"] and event_id in controller_events:
        recovered_event = controller_events[event_id]
        conversation["events"] = list(durable_by_id.values()) + [
            item for item_id, item in controller_events.items() if item_id not in durable_by_id
        ]
        conversation["processed_event_ids"] = list(dict.fromkeys(
            [item_id for item_id in conversation["processed_event_ids"] if item_id]
            + list(controller_events)
        ))
        conversation["response_count"] = max(
            int(conversation.get("response_count", 0) or 0),
            int(lead.get("response_count", 0) or 0),
            sum(
                1
                for item in conversation["events"]
                if str(item.get("direction") or "inbound").strip().lower() == "inbound"
            ),
        )
        inbound_events = [
            item for item in conversation["events"]
            if str(item.get("direction") or "inbound").strip().lower() == "inbound"
        ]
        if inbound_events:
            conversation["last_inbound_at"] = str(inbound_events[-1].get("at") or "").strip() or conversation.get("last_inbound_at")
        updated = dict(lead)
        updated["conversation_events"] = list(conversation["events"])
        updated["response_count"] = conversation["response_count"]
        stored = db.update_payload(opportunity_id, updated) or updated
        conversation["events"] = list(stored.get("conversation_events") or conversation["events"])
        conversation["updated_at"] = _now()
        _save(db, state)
        return dict(conversation)
    conversation["processed_event_ids"] = [
        item_id for item_id in conversation["processed_event_ids"] if item_id != event_id
    ]
    durable_by_id = {
        str(item.get("event_id") or "").strip(): dict(item)
        for item in durable_events
        if isinstance(item, Mapping) and str(item.get("event_id") or "").strip()
    }
    state_events = conversation.get("events")
    state_events = state_events if isinstance(state_events, list) else []
    merged_events = list(durable_by_id.values())
    seen_event_ids = set(durable_by_id)
    for item in state_events:
        if not isinstance(item, Mapping):
            continue
        existing_event_id = str(item.get("event_id") or "").strip()
        if existing_event_id and existing_event_id not in seen_event_ids:
            merged_events.append(dict(item))
            seen_event_ids.add(existing_event_id)
    conversation["events"] = merged_events
    conversation["processed_event_ids"] = list(dict.fromkeys(
        [str(item).strip() for item in conversation.get("processed_event_ids", []) if str(item).strip()]
        + list(seen_event_ids)
    ))
    durable_response_count = int(lead.get("response_count", 0) or 0)
    inbound_event_count = sum(
        1 for item in merged_events
        if isinstance(item, Mapping) and str(item.get("direction") or "inbound").strip().lower() == "inbound"
    )
    conversation["response_count"] = max(
        int(conversation.get("response_count", 0) or 0),
        durable_response_count,
        inbound_event_count,
    )
    classified = str(outcome or _classify(text)).strip().lower()
    terminal_lifecycle_states = {"converted", "closed_lost", "disqualified", "stopped", "referred"}
    current_lifecycle_state = str(lead.get("revenue_lifecycle_state") or "").strip().lower()
    if current_lifecycle_state in terminal_lifecycle_states:
        event = {"event_id": event_id, "direction": "inbound", "at": _now(), "text": str(text or ""), "outcome": classified, "ignored_after_terminal_state": current_lifecycle_state}
        if objection:
            event["objection"] = str(objection)
        conversation["events"].append(event)
        conversation["processed_event_ids"].append(event_id)
        conversation["last_inbound_at"] = event["at"]
        conversation["response_count"] = int(conversation.get("response_count", 0) or 0) + 1
        conversation["outreach_route"] = lead.get("outreach_route")
        conversation["next_action"] = "stop"
        conversation["updated_at"] = _now()
        _save(db, state)
        return dict(conversation)
    event = {"event_id": event_id, "direction": "inbound", "at": _now(), "text": str(text or ""), "outcome": classified}
    if objection: event["objection"] = str(objection)
    conversation["events"].append(event); conversation["processed_event_ids"].append(event_id); conversation["last_inbound_at"] = event["at"]; conversation["response_count"] = int(conversation.get("response_count", 0) or 0) + 1
    switched_route, switch_evidence = _route_switch(lead, suggested_route)
    updated = dict(lead); updated.update({"conversation_id": conversation_id, "conversation_events": list(conversation["events"]), "response_count": conversation["response_count"], "last_response_at": event["at"], "last_response_outcome": classified, "outreach_state": classified, "revenue_lifecycle_state": "conversation_active"})
    if switched_route:
        history = list(updated.get("route_switch_history") or []) if isinstance(updated.get("route_switch_history"), list) else []
        history.append({"at": event["at"], "from": updated.get("outreach_route"), "to": switched_route, "evidence": switch_evidence}); updated["route_switch_history"] = history; updated["outreach_route"] = switched_route; updated["active_route"] = switched_route
    if switch_evidence and not switched_route: conversation.setdefault("warnings", []).append(switch_evidence)
    should_follow_up = classified in {"interested", "replied", "objection"}
    if classified in STOP_STATES or classified == "opted_out":
        updated["revenue_lifecycle_state"] = "closed_lost" if classified != "converted" else "converted"; updated["outreach_stop_reason"] = classified; updated["next_follow_up_at"] = None; updated["follow_up_due"] = False
    elif should_follow_up:
        updated["next_follow_up_at"] = _now(); updated["follow_up_due"] = True; updated["outreach_state"] = "awaiting_response"
    stored = db.update_payload(opportunity_id, updated) or updated
    if should_follow_up:
        enqueue(db, "follow_up", {"lead": stored, "outcome": classified, "objection": objection or (text if classified == "objection" else ""), "conversation_id": conversation_id, "inbound_event_id": event_id, "execute": True, "authorized": True, "authorized_by_role": CLOSER_ROLE}, priority=10, dedupe_key=f"conversation_followup:{opportunity_id}:{event_id}")
    conversation["outreach_route"] = stored.get("outreach_route"); conversation["next_action"] = "stop" if classified in STOP_STATES or classified == "opted_out" else "closer_follow_up"; conversation["updated_at"] = _now(); _save(db, state)
    return dict(conversation)

def due_followups(db, *, now: Optional[datetime] = None, limit: int = 100) -> list[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc); due: list[Dict[str, Any]] = []
    terminal_lifecycle_states = {"converted", "referred", "closed_lost", "disqualified", "stopped"}
    for lead in db.all_leads():
        if len(due) >= limit or lead.get("follow_up_due") is not True or str(lead.get("outreach_state") or "").lower() in STOP_STATES or str(lead.get("revenue_lifecycle_state") or "").strip().lower() in terminal_lifecycle_states: continue
        raw = str(lead.get("next_follow_up_at") or "").strip()
        if not raw: continue
        try: when = datetime.fromisoformat(raw.replace("Z", "+00:00")); when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except ValueError: continue
        if when <= now: due.append(dict(lead))
    return due

def enqueue_due_followups(db: Any, *, now: Optional[datetime] = None, limit: int = 100) -> int:
    from .browser_revenue_inbound import poll_browser_revenue_inbound
    poll_browser_revenue_inbound(db, limit=limit); queued = 0
    for lead in due_followups(db, now=now, limit=limit):
        fingerprint = str(lead.get("fingerprint") or "").strip()
        if not fingerprint: continue
        due_at = str(lead.get("next_follow_up_at") or "").strip()
        enqueue(db, "follow_up", {"lead": lead, "outcome": "no_response", "execute": True, "authorized": True, "authorized_by_role": CLOSER_ROLE}, priority=10, dedupe_key=f"scheduled_followup:{fingerprint}:{due_at}"); queued += 1
    return queued

def objection_reply(text: str, route: str) -> str:
    return objection_response(text, route)
