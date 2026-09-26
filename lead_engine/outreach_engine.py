"""Evidence-grounded autonomous outreach decisioning."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional
STOP_STATES = frozenset({"declined", "opted_out", "irrelevant", "exhausted", "converted"})
ACTIVE_STATES = frozenset({"ready", "drafted", "sent", "replied", "interested", "objection"})
CADENCE_DAYS = (0, 3, 7, 14)
ROUTES = frozenset({"Thorio", "Shiftr", "Paxus", "Astrivon Labs"})
@dataclass(frozen=True)
class OutreachDecision:
    route: str
    contact_name: str
    contact_email: str
    subject: str
    body: str
    evidence_refs: tuple[str, ...]
    buying_signal: str
    next_state: str
    next_follow_up_at: Optional[str]
    stop_reason: Optional[str]
class OutreachContractError(ValueError): pass
def _text(value: Any) -> str: return str(value or "").strip()
def _research(lead: Mapping[str, Any]) -> Mapping[str, Any]:
    value = lead.get("company_research"); return value if isinstance(value, Mapping) else {}
def _routes(lead: Mapping[str, Any]) -> list[str]:
    raw = lead.get("potential_routes")
    if isinstance(raw, str): raw = [raw]
    if not isinstance(raw, Iterable) or isinstance(raw, Mapping): raw = []
    return list(dict.fromkeys(str(route).strip() for route in raw if str(route).strip() in ROUTES))
def _verified_research_mapping(lead: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = lead.get(key); return value if isinstance(value, Mapping) else {}
def _research_ref(mapping: Mapping[str, Any]) -> str:
    for key in ("evidence_url", "source_url", "evidence_ref", "source_id"):
        ref = _text(mapping.get(key))
        if ref: return ref
    return ""
def _section_verified(mapping: Mapping[str, Any]) -> bool:
    status = _text(mapping.get("verification_status") or mapping.get("status")).lower()
    return mapping.get("verified") is True or status in {"verified", "research_verified", "complete"}
def _verified_buying_signal(lead: Mapping[str, Any]) -> str:
    verified = lead.get("research_verified_fields"); verified_set = {str(item).strip() for item in verified} if isinstance(verified, (list, tuple, set)) else set()
    for mapping_key, field in (("current_intent_research", "current_need"), ("business_need_research", "business_need"), ("business_need_research", "current_need"), ("route_research", "business_need")):
        if mapping_key not in verified_set: continue
        research = _verified_research_mapping(lead, mapping_key); value = _text(research.get(field))
        if value and _section_verified(research) and _research_ref(research): return value
    raise OutreachContractError("A current need or recent inquiry must be explicitly researched, verified, and backed by provenance before outreach")
def _evidence_refs(lead: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []; research = _research(lead)
    for key in ("decision_maker_evidence", "company_verification_evidence"):
        value = research.get(key)
        if isinstance(value, (list, tuple)): refs.extend(_text(item) for item in value if _text(item))
        else:
            ref = _text(value)
            if ref: refs.append(ref)
    for mapping_key in ("current_intent_research", "business_need_research", "route_research"):
        ref = _research_ref(_verified_research_mapping(lead, mapping_key))
        if ref: refs.append(ref)
    for event in lead.get("evidence_events", []) if isinstance(lead.get("evidence_events"), list) else []:
        if isinstance(event, Mapping):
            ref = _text(event.get("source_url") or event.get("url") or event.get("source_id"))
            if ref: refs.append(ref)
    return tuple(dict.fromkeys(refs))
def _route_verified(lead: Mapping[str, Any], route: str) -> bool:
    qualification = lead.get("qualification_results")
    if not isinstance(qualification, Mapping): return False
    result = qualification.get(route)
    if not isinstance(result, Mapping) or result.get("qualified") is not True: return False
    route_research = result.get("route_research")
    if not isinstance(route_research, Mapping) or route_research.get("verified") is not True: return False
    if route == "Paxus" and result.get("true_referral") is not True: return False
    return True
def choose_route(lead: Mapping[str, Any]) -> str:
    routes = _routes(lead)
    if not routes:
        active_route = _text(lead.get("outreach_route"))
        if active_route in ROUTES and _route_verified(lead, active_route): return active_route
        raise OutreachContractError("No independently verified outreach destination is available")
    for route in routes:
        if _route_verified(lead, route): return route
    raise OutreachContractError("No route has an independently verified qualification result")
def _offer(route: str) -> str: return {"Thorio": "a verified remote tech hiring channel", "Shiftr": "AI, software, engineering, or dedicated-team support through the appropriate partner", "Paxus": "vetted remote technology talent through the appropriate referral process", "Astrivon Labs": "AI/ML, computer vision, business automation, product development, or B2B outreach and lead-generation infrastructure through Astrivon Labs"}[route]
def _subject(route: str, signal: str) -> str:
    short = signal.rstrip(".!?")
    if len(short) > 72: short = short[:69].rstrip() + "..."
    return f"Re: {short}" if short else f"A possible fit for {route}"
def _sales_body(route: str, contact_name: str, company: str, signal: str) -> str: return f"Hi {contact_name},\n\nI saw that {signal.strip().rstrip('.!?')}. If that is still a priority at {company}, I may be able to help.\n\nI work with {_offer(route)}. Based on the researched need, it looks worth a quick conversation to see whether there is a real fit.\n\nWould it be useful if I sent over the most relevant option?\n\nBest,\nThorio"
def _require_research_contract(lead: Mapping[str, Any]) -> Mapping[str, Any]:
    if _text(lead.get("research_status")).lower() not in {"complete", "research_complete"}: raise OutreachContractError("Completed research is required before outreach")
    research = _research(lead)
    if not research: raise OutreachContractError("Completed company research is required before outreach")
    if research.get("company_verified") is not True: raise OutreachContractError("Verified company research is required before outreach")
    if not _text(research.get("decision_maker")) or not _text(research.get("decision_maker_evidence")): raise OutreachContractError("Verified decision-maker identity and evidence are required")
    if _text(research.get("decision_maker_verification_status")).lower() != "verified": raise OutreachContractError("Decision-maker verification must be explicitly verified")
    return research
def build_outreach_decision(lead: Mapping[str, Any], *, now: Optional[datetime] = None) -> OutreachDecision:
    research = _require_research_contract(lead); contact_name = _text(research.get("decision_maker")); contact_email = _text(research.get("decision_maker_email") or research.get("contact_email") or lead.get("contact_email"))
    if not contact_email: raise OutreachContractError("Verified decision-maker contact email is required")
    signal = _verified_buying_signal(lead); route = choose_route(lead); company = _text(lead.get("company"))
    if not company: raise OutreachContractError("Verified company identity is required")
    body = _sales_body(route, contact_name, company, signal); current = _text(lead.get("outreach_state") or "ready").lower()
    if current in STOP_STATES: return OutreachDecision(route, contact_name, contact_email, "", "", _evidence_refs(lead), signal, current, None, current)
    now = now or datetime.now(timezone.utc); attempt = int(lead.get("outreach_attempt", 0) or 0); next_at = None if attempt >= len(CADENCE_DAYS) - 1 else (now + timedelta(days=CADENCE_DAYS[attempt + 1])).isoformat()
    return OutreachDecision(route, contact_name, contact_email, _subject(route, signal), body, _evidence_refs(lead), signal, "drafted", next_at, None)
def objection_response(objection: str, route: str) -> str:
    text = _text(objection).lower()
    if any(token in text for token in ("not interested", "no thanks", "stop", "remove me")): return "Understood. I will not follow up further."
    if "price" in text or "cost" in text: return f"Understood. I do not want to guess at fit or pricing. I can share the {route} option only if it matches the researched need."
    if any(token in text for token in ("later", "not now", "timing")): return "Understood. I can leave this here and follow up later rather than assume the timing is right."
    return "Thanks for the context. I will keep the response grounded in the verified research rather than make assumptions."
def apply_outcome(lead: Mapping[str, Any], outcome: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    outcome = _text(outcome).lower(); allowed = STOP_STATES | ACTIVE_STATES | {"no_response"}
    if outcome not in allowed: raise OutreachContractError(f"Unsupported outreach outcome: {outcome}")
    updated = dict(lead); now = now or datetime.now(timezone.utc); history = list(lead.get("outreach_history") or []) if isinstance(lead.get("outreach_history"), list) else []
    if str(lead.get("sales_eligibility") or "").strip().lower() == "eligible" and outcome not in STOP_STATES:
        verified_signal = _verified_buying_signal(lead)
        updated["current_need"] = verified_signal
        updated["verified_follow_up_signal"] = verified_signal
    history.append({"at": now.isoformat(), "outcome": outcome}); updated["outreach_history"] = history; updated["outreach_state"] = outcome
    if outcome in STOP_STATES: updated["outreach_stop_reason"] = outcome; updated["next_follow_up_at"] = None
    elif outcome == "no_response":
        attempt = int(lead.get("outreach_attempt", 0) or 0) + 1; updated["outreach_attempt"] = attempt
        if attempt >= len(CADENCE_DAYS): updated["outreach_state"] = "exhausted"; updated["outreach_stop_reason"] = "exhausted"; updated["next_follow_up_at"] = None
        else: updated["outreach_state"] = "ready"; updated["next_follow_up_at"] = (now + timedelta(days=CADENCE_DAYS[attempt])).isoformat()
    return updated
