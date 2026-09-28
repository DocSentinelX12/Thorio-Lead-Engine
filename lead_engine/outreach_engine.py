"""Evidence-grounded autonomous outreach decisioning."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from .sales_closer_intelligence import build_commercial_strategy, build_objection_response, evaluate_closer_message
STOP_STATES = frozenset({"declined", "opted_out", "irrelevant", "exhausted", "converted"})
ACTIVE_STATES = frozenset({"ready", "drafted", "sent", "replied", "interested", "objection"})
CADENCE_DAYS = (0, 3, 7, 14)
ROUTES = frozenset({"Thorio", "Shiftr", "Paxus", "Astrivon Labs"})
@dataclass(frozen=True)
class OutreachDecision:
    route: str; contact_name: str; contact_email: str; subject: str; body: str; evidence_refs: tuple[str, ...]; buying_signal: str; next_state: str; next_follow_up_at: Optional[str]; stop_reason: Optional[str]; commercial_strategy: Mapping[str, Any]
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
    evidence = mapping.get("evidence")
    if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes, Mapping)):
        for item in evidence:
            if isinstance(item, Mapping):
                for key in ("url", "evidence_url", "source_url", "evidence_ref", "source_id"):
                    ref = _text(item.get(key))
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
    return tuple(dict.fromkeys(refs))
def _route_verified(lead: Mapping[str, Any], route: str) -> bool:
    qualification = lead.get("qualification_results")
    if not isinstance(qualification, Mapping): return False
    result = qualification.get(route)
    if not isinstance(result, Mapping) or result.get("qualified") is not True: return False
    route_research = result.get("route_research")
    if not isinstance(route_research, Mapping) or route_research.get("verified") is not True: return False
    if route == "Paxus" and result.get("true_referral") is not True: return False
    if route == "Astrivon Labs" and result.get("service_fit_verified") is not True: return False
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
def _offer(route: str) -> str: return {"Astrivon Labs": "AI/ML, computer vision, business automation, product development, and B2B outreach and lead-generation infrastructure", "Thorio": "a verified remote tech hiring channel", "Shiftr": "AI, software, engineering, or dedicated-team support through the appropriate partner", "Paxus": "vetted remote technology talent through the appropriate referral process"}[route]
def _subject(route: str, signal: str) -> str:
    short = signal.rstrip(".!?")
    if len(short) > 72: short = short[:69].rstrip() + "..."
    return f"Re: {short}" if short else f"A possible fit for {route}"
def _sales_body(route: str, contact_name: str, company: str, signal: str, strategy: Mapping[str, Any]) -> str:
    clean_signal = signal.strip().rstrip(".!?")
    state = _text(strategy.get("conversation_state")).lower()
    impact = _text(strategy.get("verified_business_impact")).rstrip(".!?")
    cost_of_inaction = _text(strategy.get("verified_cost_of_inaction")).rstrip(".!?")
    unknowns = strategy.get("unknowns")
    unknown_list = [str(item).strip() for item in unknowns if str(item).strip()] if isinstance(unknowns, (list, tuple)) else []
    conversation_intelligence = strategy.get("conversation_intelligence")
    selected_question = _text(conversation_intelligence.get("next_best_question")) if isinstance(conversation_intelligence, Mapping) else ""
    discovery_question = selected_question or (unknown_list[0] if unknown_list else "What is the main outcome you would want to improve?")
    selected_action = _text(conversation_intelligence.get("next_best_action")) if isinstance(conversation_intelligence, Mapping) else ""
    research_reentry = strategy.get("research_reentry")
    reentry_required = isinstance(research_reentry, Mapping) and research_reentry.get("recommended") is True
    if state == "interested":
        evidence_line = f" The research also identifies this business impact: {impact}." if impact else ""
        action_line = f" The next step is to {selected_action.replace('_', ' ')}." if selected_action else ""
        return f"Hi {contact_name},\n\nThanks for the interest. Based on the researched need around {clean_signal}.{evidence_line}{action_line} The useful next step is to clarify the outcome that matters most and whether there is a real fit.\n\n{discovery_question}\n\nI can walk through the relevant {route} option and keep the discussion focused on fit, evidence, expected value, and what would need to be true for it to make sense.\n\nWould a brief conversation be useful?\n\nBest,\nThorio"
    if state == "awaiting_response":
        impact_line = f" The researched impact is {impact}." if impact else ""
        reentry_line = " I will keep this to discovery rather than make an unsupported factual claim." if reentry_required else ""
        return f"Hi {contact_name},\n\nFollowing up on the researched need around {clean_signal}.{impact_line} I do not want to assume the priority is still active.{reentry_line} {discovery_question}\n\nIf it is still relevant, would it be useful to compare the desired outcome with the most appropriate {route} option?\n\nBest,\nThorio"
    if state in {"replied", "objection", "timing"}:
        impact_line = f" The verified business impact is {impact}." if impact else ""
        reentry_line = " I will keep this to discovery until the missing evidence is established." if reentry_required else ""
        return f"Hi {contact_name},\n\nThanks for the context. I want to keep this grounded in what is actually true for {company}. The researched need is {clean_signal}.{impact_line}{reentry_line}\n\n{discovery_question}\n\nIf the need is still active, would it be useful to take a short look at fit and the decision process before discussing a solution?\n\nBest,\nThorio"
    impact_line = f" Research also verifies this business impact: {impact}." if impact else ""
    inaction_line = f" Research also documents this cost of inaction: {cost_of_inaction}." if cost_of_inaction else ""
    reentry_line = " I will keep this to discovery rather than fill that evidence gap with an assumption." if reentry_required else ""
    return f"Hi {contact_name},\n\nI saw that {clean_signal}. If that is still a priority at {company}, I may be able to help.{impact_line}{inaction_line}\n\nRather than assume what matters commercially, I would like to understand the outcome you need and whether the researched issue is creating a meaningful business consequence.{reentry_line} {discovery_question}\n\nI work with {_offer(route)}. If there is a genuine fit, would it be useful if I sent over the most relevant option or arranged a brief introductory conversation?\n\nBest,\nThorio"
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
    strategy = build_commercial_strategy(lead)
    body = _sales_body(route, contact_name, company, signal, strategy)
    message_quality = evaluate_closer_message(body, strategy, signal)
    strategy = {**strategy, "message_quality": message_quality}
    if not message_quality["passed"]:
        raise OutreachContractError("Closer message failed commercial truthfulness gate: " + ",".join(message_quality["violations"]))
    current = _text(lead.get("outreach_state") or "ready").lower()
    if current in STOP_STATES: return OutreachDecision(route, contact_name, contact_email, "", "", _evidence_refs(lead), signal, current, None, current, strategy)
    now = now or datetime.now(timezone.utc); attempt = int(lead.get("outreach_attempt", 0) or 0); next_at = None if attempt >= len(CADENCE_DAYS) - 1 else (now + timedelta(days=CADENCE_DAYS[attempt + 1])).isoformat()
    return OutreachDecision(route, contact_name, contact_email, _subject(route, signal), body, _evidence_refs(lead), signal, "drafted", next_at, None, strategy)
def objection_response(objection: str, route: str, *, lead: Mapping[str, Any] | None = None) -> str:
    return build_objection_response(objection, route, lead=lead)
def apply_outcome(lead: Mapping[str, Any], outcome: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    outcome = _text(outcome).lower(); allowed = STOP_STATES | ACTIVE_STATES | {"no_response"}
    if outcome not in allowed: raise OutreachContractError(f"Unsupported outreach outcome: {outcome}")
    updated = dict(lead); now = now or datetime.now(timezone.utc); history = list(lead.get("outreach_history") or []) if isinstance(lead.get("outreach_history"), list) else []
    if str(lead.get("sales_eligibility") or "").strip().lower() == "eligible" and outcome not in STOP_STATES:
        verified_signal = _verified_buying_signal(lead); updated["current_need"] = verified_signal; updated["verified_follow_up_signal"] = verified_signal
    history.append({"at": now.isoformat(), "outcome": outcome}); updated["outreach_history"] = history; updated["outreach_state"] = outcome
    if outcome in STOP_STATES: updated["outreach_stop_reason"] = outcome; updated["next_follow_up_at"] = None
    elif outcome == "no_response":
        attempt = int(lead.get("outreach_attempt", 0) or 0) + 1; updated["outreach_attempt"] = attempt
        if attempt >= len(CADENCE_DAYS): updated["outreach_state"] = "exhausted"; updated["outreach_stop_reason"] = "exhausted"; updated["next_follow_up_at"] = None
        else: updated["outreach_state"] = "ready"; updated["next_follow_up_at"] = (now + timedelta(days=CADENCE_DAYS[attempt])).isoformat()
    return updated
