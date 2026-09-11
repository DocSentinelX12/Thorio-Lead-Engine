"""Evidence-grounded autonomous outreach decisioning.

This module owns the revenue-stage decision model: route selection, evidence-
grounded personalization, objection handling, cadence, stop states, and outcome
tracking. It never invents facts or silently changes a lead's qualification.
Transport adapters remain outside this module so the same decision engine can
be exercised deterministically in tests and by the runtime's permitted account
connectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional


STOP_STATES = frozenset({"declined", "opted_out", "irrelevant", "exhausted", "converted"})
ACTIVE_STATES = frozenset({"ready", "drafted", "sent", "replied", "interested", "objection"})
CADENCE_DAYS = (0, 3, 7, 14)


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
    """Raised when outreach cannot be safely produced from the supplied evidence."""


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
    allowed = {"Thorio", "Shiftr", "Paxus"}
    return [str(route).strip() for route in raw if str(route).strip() in allowed]


def _signal(lead: Mapping[str, Any]) -> str:
    for key in ("current_need", "recent_inquiry", "signal", "evidence", "need"):
        value = _text(lead.get(key))
        if value:
            return value
    research = _research(lead)
    for key in ("current_need", "recent_inquiry", "hiring_signal", "business_problem"):
        value = _text(research.get(key))
        if value:
            return value
    return ""


def _evidence_refs(lead: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for event in lead.get("evidence_events", []) if isinstance(lead.get("evidence_events"), list) else []:
        if isinstance(event, Mapping):
            ref = _text(event.get("source_url") or event.get("url") or event.get("source_id"))
            if ref:
                refs.append(ref)
    research = _research(lead)
    for key in ("decision_maker_evidence", "evidence_url", "source_url"):
        ref = _text(research.get(key))
        if ref:
            refs.append(ref)
    return tuple(dict.fromkeys(refs))


def choose_route(lead: Mapping[str, Any]) -> str:
    routes = _routes(lead)
    if not routes:
        raise OutreachContractError("No verified outreach destination is available")
    paxus = (lead.get("qualification_results") or {}).get("Paxus", {})
    if "Paxus" in routes and isinstance(paxus, Mapping) and paxus.get("true_referral"):
        return "Paxus"
    for route in ("Thorio", "Shiftr", "Paxus"):
        if route in routes:
            return route
    raise OutreachContractError("No supported outreach destination is available")


def _offer(route: str) -> str:
    return {
        "Thorio": "a verified remote tech hiring channel",
        "Shiftr": "AI, software, engineering, or dedicated-team support through the appropriate partner",
        "Paxus": "vetted remote technology talent through the appropriate referral process",
    }[route]


def _subject(route: str, signal: str) -> str:
    short = signal.rstrip(".!?")
    if len(short) > 72:
        short = short[:69].rstrip() + "..."
    return f"Re: {short}" if short else f"A possible fit for {route}"


def _humanize_signal(signal: str) -> str:
    text = signal.strip().rstrip(".!?")
    if not text:
        return "the need you mentioned"
    return text[0].lower() + text[1:]


def _sales_body(route: str, contact_name: str, company: str, signal: str) -> str:
    need = _humanize_signal(signal)
    offer = _offer(route)
    return (
        f"Hi {contact_name},\n\n"
        f"I saw that {need}. If that is still a priority at {company}, I may be able to help.\n\n"
        f"I work with {offer}. Based on what you shared, it looks worth a quick conversation to see whether there is a real fit.\n\n"
        f"Would it be useful if I sent over the most relevant option?\n\n"
        f"Best,\nThorio"
    )


def build_outreach_decision(lead: Mapping[str, Any], *, now: Optional[datetime] = None) -> OutreachDecision:
    if _text(lead.get("research_status")).lower() != "complete":
        raise OutreachContractError("Completed company research is required before outreach")
    research = _research(lead)
    contact_name = _text(research.get("decision_maker") or lead.get("contact_name"))
    contact_email = _text(research.get("contact_email") or lead.get("contact_email"))
    contact_evidence = _text(research.get("decision_maker_evidence"))
    if not contact_name or not contact_evidence:
        raise OutreachContractError("Verified decision-maker identity and evidence are required")
    signal = _signal(lead)
    if not signal:
        raise OutreachContractError("A demonstrated current need or recent inquiry is required")
    route = choose_route(lead)
    company = _text(lead.get("company") or research.get("company")) or "your team"
    body = _sales_body(route, contact_name, company, signal)
    current = _text(lead.get("outreach_state") or "ready").lower()
    if current in STOP_STATES:
        return OutreachDecision(route, contact_name, contact_email, "", "", _evidence_refs(lead), signal, current, None, current)
    now = now or datetime.now(timezone.utc)
    attempt = int(lead.get("outreach_attempt", 0) or 0)
    next_at = None if attempt >= len(CADENCE_DAYS) - 1 else (now + timedelta(days=CADENCE_DAYS[attempt + 1])).isoformat()
    return OutreachDecision(
        route=route,
        contact_name=contact_name,
        contact_email=contact_email,
        subject=_subject(route, signal),
        body=body,
        evidence_refs=_evidence_refs(lead),
        buying_signal=signal,
        next_state="drafted",
        next_follow_up_at=next_at,
        stop_reason=None,
    )


def objection_response(objection: str, route: str) -> str:
    text = _text(objection).lower()
    if any(token in text for token in ("not interested", "no thanks", "stop", "remove me")):
        return "Understood. I will not follow up further."
    if "price" in text or "cost" in text:
        return f"Understood. I do not want to guess at fit or pricing. I can share the {route} option only if it matches the need you described."
    if any(token in text for token in ("later", "not now", "timing")):
        return "Understood. I can leave this here and follow up later rather than assume the timing is right."
    return "Thanks for the context. I will keep the response grounded in what you actually need rather than make assumptions."


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
