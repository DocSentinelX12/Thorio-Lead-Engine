"""Stateless professional logic for high-volume discovery and social research.

The handlers consume observed evidence and return auditable findings. They do not
invent facts, access credentials, or perform outreach transport. Revenue-stage
decisioning is delegated to outreach_engine so cadence, stop states, routing,
and evidence-grounded copy remain deterministic and testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

from .outreach_engine import OutreachContractError, apply_outcome, build_outreach_decision, objection_response
from .agent_queue import enqueue
from .active_processing import airtable_integrity, priority, routing, verification

DISCOVERY_TARGETS = {
    "engineering_demand_discovery": ("software", "engineer", "developer", "backend", "frontend", "full stack", "devops", "platform", "engineering"),
    "ai_demand_discovery": ("ai", "artificial intelligence", "machine learning", "ml", "llm", "agent", "automation", "data scientist", "data engineering"),
    "product_design_demand_discovery": ("product manager", "product", "ux", "ui", "design", "designer", "user experience"),
    "contract_team_demand_discovery": ("contract", "contractor", "staff augmentation", "outsourc", "dedicated team", "development team", "agency", "freelance"),
    "recent_inquiry_discovery": ("looking for", "need a", "need an", "seeking", "any recommendations", "can anyone recommend", "hiring", "we are hiring", "we're hiring", "urgent", "immediately"),
}

SOCIAL_TARGETS = {
    "social_intelligence": (),
    "social_hiring_research": ("hiring", "hire", "recruit", "recruiting", "open role", "opening", "job", "jobs", "career", "careers"),
    "social_decision_maker_research": ("founder", "co-founder", "ceo", "cto", "cio", "cpo", "vp engineering", "head of engineering", "engineering manager", "recruiter", "talent"),
    "social_inquiry_research": ("looking for", "need", "seeking", "recommend", "recommendation", "help wanted", "anyone know", "who can", "vendor", "team"),
    "social_company_context": ("company", "startup", "saas", "product", "team", "funding", "launch", "customer", "customers"),
}


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(v) for v in value)
    return str(value or "").strip()


def _events(payload: Mapping[str, Any]) -> list[Dict[str, Any]]:
    raw = payload.get("evidence_events", payload.get("events", []))
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _recent(event: Mapping[str, Any]) -> bool:
    raw = event.get("observed_at") or event.get("discovery_timestamp") or event.get("collected_at") or event.get("published_at")
    if not raw:
        return False
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - value).total_seconds() <= 30 * 86400
    except ValueError:
        return False


def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", lowered)]


def _fingerprint(payload: Mapping[str, Any]) -> str:
    lead = payload.get("lead")
    if isinstance(lead, Mapping):
        return str(lead.get("fingerprint") or "").strip()
    return str(payload.get("fingerprint") or "").strip()


def discovery_finding(agent: str, payload: Mapping[str, Any], db: Any = None) -> Dict[str, Any]:
    events = _events(payload)
    lead = payload.get("lead") if isinstance(payload.get("lead"), Mapping) else {}
    if not events and lead:
        events = [dict(lead)]
    terms = DISCOVERY_TARGETS[agent]
    findings = []
    for event in events:
        text = _text(event.get("signal") or event.get("evidence") or event)
        matches = _matches(text, terms)
        if matches:
            findings.append({"matches": matches, "source": event.get("source") or event.get("provider"), "url": event.get("url") or event.get("source_url"), "recent": _recent(event), "evidence": text[:2000]})
    recent_count = sum(item["recent"] for item in findings)
    fingerprint = _fingerprint(payload)
    handoff = None
    if findings and fingerprint and db is not None:
        stored_lead = db.get(fingerprint) or dict(lead)
        enqueue(db, "qualification_a", {"lead": stored_lead, "evidence_events": events, "discovery_agent": agent, "discovery_findings": findings}, priority=4, dedupe_key=f"qualification_a:{fingerprint}")
        handoff = "qualification_a"
    return {"agent": agent, "role": "discovery_intelligence", "fingerprint": fingerprint, "target": agent.removesuffix("_discovery"), "matched_event_count": len(findings), "recent_event_count": recent_count, "findings": findings, "requires_verification": bool(findings), "no_match_is_not_rejection": True, "handoff": handoff}


def social_research(agent: str, payload: Mapping[str, Any], db: Any = None) -> Dict[str, Any]:
    events = _events(payload)
    lead = payload.get("lead") if isinstance(payload.get("lead"), Mapping) else {}
    if not events and lead:
        events = [dict(lead)]
    terms = SOCIAL_TARGETS[agent]
    findings = []
    sources = set()
    recent = 0
    for event in events:
        text = _text(event.get("signal") or event.get("evidence") or event)
        if not text:
            continue
        sources.add(str(event.get("source") or event.get("provider") or "unknown"))
        matches = _matches(text, terms) if terms else []
        if terms and not matches:
            continue
        is_recent = _recent(event)
        recent += int(is_recent)
        findings.append({"matches": matches, "source": event.get("source") or event.get("provider"), "url": event.get("url") or event.get("source_url"), "recent": is_recent, "evidence": text[:2000]})
    fingerprint = _fingerprint(payload)
    handoff = None
    if findings and fingerprint and db is not None:
        stored_lead = db.get(fingerprint) or dict(lead)
        enqueue(db, "company_research", {"lead": stored_lead, "evidence_events": events, "social_research_agent": agent, "social_findings": findings}, priority=7, dedupe_key=f"company_research:{fingerprint}")
        handoff = "company_research"
    return {"agent": agent, "role": "social_research", "fingerprint": fingerprint, "matched_event_count": len(findings), "recent_event_count": recent, "source_count": len(sources), "sources": sorted(sources), "findings": findings, "research_status": "evidence_found" if findings else "research_required", "verification_required": True, "fabricated_fields": [], "handoff": handoff}


def company_research(payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    """Persist an evidence-grounded research packet and hand it to validation."""
    lead = payload.get("lead") if isinstance(payload.get("lead"), Mapping) else payload
    events = _events(payload)
    company = str(lead.get("company") or "").strip()
    source_url = str(lead.get("source_url") or lead.get("url") or "").strip()
    person = str(lead.get("contact_name") or lead.get("person") or "").strip()
    signal = str(lead.get("signal") or lead.get("evidence") or "").strip()
    evidence = str(lead.get("evidence") or "").strip()
    fingerprint = str(lead.get("fingerprint") or "").strip()
    if not fingerprint:
        raise ValueError("company_research requires lead fingerprint")
    facts: Dict[str, Any] = {
        "company_verified": bool(company),
        "company_identity_evidence": f"Observed company name: {company}" if company else "",
        "business_context": signal,
        "current_need_evidence": signal,
        "recent_activity_evidence": evidence,
        "source_url": source_url,
        "evidence_event_count": len(events),
        "researched_at": datetime.now(timezone.utc).isoformat(),
        "fabricated_fields": [],
    }
    if person:
        facts["decision_maker"] = person
        facts["decision_maker_evidence"] = f"Named person was directly observed in collector evidence: {person}."
        facts["decision_maker_verification_status"] = "observed_needs_role_verification"
    status = "complete" if facts["company_verified"] and facts.get("decision_maker") and facts.get("decision_maker_evidence") and facts.get("decision_maker_verification_status") == "verified" else "research_required"
    stored = ctx.db.update_payload(fingerprint, {"company_research": facts, "research_status": status, "research_verified_fields": [key for key, value in facts.items() if value not in (None, "", [], {}, ())]})
    if stored is None:
        raise ValueError(f"Lead not found for company research: {fingerprint}")
    enqueue(ctx.db, "qualification_b", {"lead": stored, "prior_result": {"agent": "company_research", "research_status": status}, "evidence_events": events, "research_result": {"status": status, "verified_fields": stored.get("research_verified_fields", [])}}, priority=9, dedupe_key=f"qualification_b:{fingerprint}")
    return {"role": "company_research", "fingerprint": fingerprint, "lead": stored, "research": facts, "research_status": status, "decision_maker_verified": facts.get("decision_maker_verification_status") == "verified", "verified_fields": stored.get("research_verified_fields", []), "fabricated_fields": [], "handoff": "qualification_b"}


def outreach_closing(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Prepare the next revenue action only after explicit user authorization."""
    if payload.get("authorized") is not True:
        raise OutreachContractError("outreach_closer requires explicit authorized=True")
    lead = payload.get("lead") if isinstance(payload.get("lead"), Mapping) else payload
    decision = build_outreach_decision(lead)
    return {"role": "outreach_closer", "lead": dict(lead), "action": "prepare_authorized_outreach", "autonomous": True, "authorized": True, "route": decision.route, "contact": {"name": decision.contact_name, "email": decision.contact_email}, "subject": decision.subject, "body": decision.body, "evidence_refs": list(decision.evidence_refs), "buying_signal": decision.buying_signal, "next_state": decision.next_state, "next_follow_up_at": decision.next_follow_up_at, "stop_reason": decision.stop_reason, "truthfulness_guard": "evidence_only"}


def follow_up_action(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Advance an existing outreach state and determine whether contact stops or continues."""
    if payload.get("authorized") is not True:
        raise OutreachContractError("follow_up requires explicit authorized=True")
    lead = payload.get("lead") if isinstance(payload.get("lead"), Mapping) else payload
    outcome = str(payload.get("outcome") or lead.get("outreach_state") or "").strip().lower()
    if not outcome:
        raise OutreachContractError("follow_up requires an observed outreach outcome")
    updated = apply_outcome(lead, outcome)
    result: Dict[str, Any] = {"role": "follow_up", "lead": updated, "autonomous": True, "authorized": True, "outreach_state": updated.get("outreach_state"), "next_follow_up_at": updated.get("next_follow_up_at"), "stop_reason": updated.get("outreach_stop_reason"), "action": "stop" if updated.get("outreach_state") in {"declined", "opted_out", "irrelevant", "exhausted", "converted"} else "prepare_authorized_follow_up", "outcome_recorded": True}
    objection = payload.get("objection")
    if objection:
        result["objection_response"] = objection_response(str(objection), str(updated.get("outreach_route") or "the selected service"))
    return result


def advanced_handler_registry():
    handlers = {}
    for agent in DISCOVERY_TARGETS:
        handlers[agent] = lambda _agent, payload, ctx, name=agent: discovery_finding(name, payload, ctx.db)
    for agent in SOCIAL_TARGETS:
        handlers[agent] = lambda _agent, payload, ctx, name=agent: social_research(name, payload, ctx.db)
    handlers["company_research"] = lambda _agent, payload, ctx: company_research(payload, ctx)
    handlers["priority"] = priority
    handlers["verification"] = verification
    handlers["routing"] = routing
    handlers["airtable_integrity"] = airtable_integrity
    handlers["outreach_closer"] = lambda _agent, payload, _ctx: outreach_closing(payload)
    handlers["follow_up"] = lambda _agent, payload, _ctx: follow_up_action(payload)
    return handlers
