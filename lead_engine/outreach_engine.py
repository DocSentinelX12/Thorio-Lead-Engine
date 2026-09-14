"""Evidence-grounded autonomous outreach decisioning.

Revenue communication may use only the completed, explicitly verified research
package. Discovery signal and raw evidence are provenance inputs, never a
fallback source for buying claims or personalization.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

STOP_STATES = frozenset({"declined", "opted_out", "irrelevant", "exhausted", "converted"})
ACTIVE_STATES = frozenset({"ready", "drafted", "sent", "replied", "interested", "objection"})
CADENCE_DAYS = (0, 3, 7, 14)
ROUTES = frozenset({"Thorio", "Shiftr", "Paxus"})

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

class OutreachContractError(ValueError):
    """Raised when outreach cannot be safely produced from verified research."""

def _text(value: Any) -> str:
    return str(value or "").strip()

def _research(lead: Mapping[str, Any]) -> Mapping[str, Any]:
    value = lead.get("company_research")
    return value if isinstance(value, Mapping) else {}

def _routes(lead: Mapping[str, Any]) -> list[str]:
    raw = lead.get("potential_routes")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable) or isinstance(raw, Mapping):
        raw = []
    return list(dict.fromkeys(str(route).strip() for route in raw if str(route).strip() in ROUTES))

def _verified_research_mapping(lead: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = lead.get(key)
    return value if isinstance(value, Mapping) else {}

def _research_ref(mapping: Mapping[str, Any]) -> str:
    for key in ("evidence_url", "source_url", "evidence_ref", "source_id"):
        ref = _text(mapping.get(key))
        if ref:
            return ref
    return ""

def _verified_buying_signal(lead: Mapping[str, Any]) -> str:
    """Return only an explicitly verified researched need or intent with provenance."""
    verified = lead.get("research_verified_fields")
    verified_set = {str(item).strip() for item in verified} if isinstance(verified, (list, tuple, set)) else set()
    candidates = (
        ("current_intent_research", "current_need"),
        ("business_need_research", "business_need"),
        ("business_need_research", "current_need"),
        ("route_research", "business_need"),
    )
    for mapping_key, field in candidates:
        if mapping_key not in verified_set:
            continue
        research = _verified_research_mapping(lead, mapping_key)
        value = _text(research.get(field))
        if value and _research_ref(research):
            return value
    raise OutreachContractError("A current need or recent inquiry must be explicitly researched, verified, and backed by provenance before outreach")

def _evidence_refs(lead: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    research = _research(lead)
    for key in ("decision_maker_evidence", "company_verification_evidence"):
        value = research.get(key)
        if isinstance(value, (list, tuple)):
            refs.extend(_text(item) for item in value if _text(item))
        else:
            ref = _text(value)
            if ref:
                refs.append(ref)
    for mapping_key in ("current_intent_research", "business_need_research", "route_research"):
        mapping = _verified_research_mapping(lead, mapping_key)
        ref = _research_ref(mapping)
        if ref:
            refs.append(ref)
    for event in lead.get("evidence_events", []) if isinstance(lead.get("evidence_events"), list) else []:
        if isinstance(event, Mapping):
            ref = _text(event.get("source_url") or event.get("url") or event.get("source_id"))
            if ref:
                refs.append(ref)
    return tuple(dict.fromkeys(refs))

def choose_route(lead: Mapping[str, Any]) -> str:
    routes = _routes(lead)
    if not routes:
        active_route = _text(lead.get("outreach_route"))
        if active_route in ROUTES:
            return active_route
        raise OutreachContractError("No verified outreach destination is available")
    qualification = lead.get("qualification_results")
    for route in routes:
        result = qualification.get(route) if isinstance(qualification, Mapping) else None
        if isinstance(result, Mapping) and result.get("qualified") is True:
            if route == "Paxus" and result.get("true_referral") is not True:
                continue
            return route
    raise OutreachContractError("No route has an independently verified qualification result")

def _offer(route: str) -> str:
    return {"Thorio": "a verified remote tech hiring channel", "Shiftr": "AI, software, engineering, or dedicated-team support through the appropriate partner", "Paxus": "vetted remote technology talent through the appropriate referral process"}[route]

def _subject(route: str, signal: str) -> str:
    short = signal.rstrip(".!?")
    if len(short) > 72:
        short = short[:69].rstrip() + "..."
    return f"Re: {short}" if short else f"A possible fit for {route}"

def _humanize_signal(signal: str) -> str:
    return signal.strip().rstrip(".!?")

def _sales_body(route: str, contact_name: str, company: str, signal: str) -> str:
    need = _humanize_signal(signal)
    offer = _offer(route)
    return (f"Hi {contact_name},\n\n"
            f"I saw that {need}. If that is still a priority at {company}, I may be able to help.\n\n"
            f"I work with {offer}. Based on the researched need, it looks worth a quick conversation to see whether there is a real fit.\n\n"
            f"Would it be useful if I sent over the most relevant option?\n\n"
            f"Best,\nThorio")

def _require_research_contract(lead: Mapping[str, Any]) -> Mapping[str, Any]:
    if _text(lead.get("research_status")).lower() not in {"complete", "research_complete"}:
        raise OutreachContractError("Completed research is required before outreach")
    research = _research(lead)
    if not research:
        raise OutreachContractError("Completed company research is required before outreach")
    if research.get("company_verified") is not True:
        raise OutreachContractError("Verified company research is required before outreach")
    if not _text(research.get("decision_maker")) or not _text(research.get("decision_maker_evidence")):
        raise OutreachContractError("Verified decision-maker identity and evidence are required")
    if _text(research.get("decision_maker_verification_status")).lower() != "verified":
        raise OutreachContractError("Decision-maker verification must be explicitly verified")
    return research

def build_outreach_decision(lead: Mapping[str, Any], *, now: Optional[datetime] = None) -> OutreachDecision:
    research = _require_research_contract(lead)
    contact_name = _text(research.get("decision_maker"))
    contact_email = _text(research.get("decision_maker_email") or research.get("contact_email") or lead.get("contact_email"))
    if not contact_email:
        raise OutreachContractError("Verified decision-maker contact email is required")
    signal = _verified_buying_signal(lead)
    route = choose_route(lead)
    company = _text(lead.get("company"))
    if not company:
        raise OutreachContractError("Verified company identity is required")
    body = _sales_body(route, contact_name, company, signal)
    current = _text(lead.get("outreach_state") or "ready").lower()
    if current in STOP_STATES:
        return OutreachDecision(route, contact_name, contact_email, "", "", _evidence_refs(lead), signal, current, None, current)
    now = now or datetime.now(timezone.utc)
    attempt = int(lead.get("outreach_attempt", 0) or 0)
    next_at = None if attempt >= len(CADENCE_DAYS) - 1 else (now + timedelta(days=CADENCE_DAYS[attempt + 1])).isoformat()
    return OutreachDecision(route, contact_name, contact_email, _subject(route, signal), body, _evidence_refs(lead), signal, "drafted", next_at, None)

def objection_response(objection: str, route: str) -> str:
    text = _text(objection).lower()
    if any(token in text for token in ("not interested", "no thanks", "stop", "remove me")):
        return "Understood. I will not follow up further."
    if "price" in text or "cost" in text:
        return f"Understood. I do not want to guess at fit or pricing. I can share the {route} option only if it matches the researched need."
    if any(token in text for token in ("later", "not now", "timing")):
        return "Understood. I can leave this here and follow up later rather than assume the timing is right."
    return "Thanks for the context. I will keep the response grounded in the verified research rather than make assumptions."

def apply_outcome(lead: Mapping[str, Any], outcome: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    outcome = _text(outcome).lower()
    allowed = STOP_STATES | ACTIVE_STATES | {"no_response"}
    if outcome not in allowed:
        raise OutreachContractError(f"Unsupported outreach outcome: {outcome}")
    updated = dict(lead)
    now = now or datetime.now(timezone.utc)
    history = list(lead.get("outreach_history") or []) if isinstance(lead.get("outreach_history"), list) else []
    history.append({"at": now.isoformat(), "outcome": outcome})
    updated["outreach_history"] = history
    updated["outreach_state"] = outcome
    if outcome in STOP_STATES:
        updated["outreach_stop_reason"] = outcome
        updated["next_follow_up_at"] = None
    elif outcome == "no_response":
        attempt = int(lead.get("outreach_attempt", 0) or 0) + 1
        updated["outreach_attempt"] = attempt
        if attempt >= len(CADENCE_DAYS):
            updated["outreach_state"] = "exhausted"
            updated["outreach_stop_reason"] = "exhausted"
            updated["next_follow_up_at"] = None
        else:
            updated["outreach_state"] = "ready"
            updated["next_follow_up_at"] = (now + timedelta(days=CADENCE_DAYS[attempt])).isoformat()
    return updated
