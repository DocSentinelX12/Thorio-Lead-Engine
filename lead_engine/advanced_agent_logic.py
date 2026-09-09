"""Stateless professional logic for high-volume discovery and social research.

The handlers consume observed evidence and return auditable findings. They do not
invent facts, access credentials, or perform outreach. Persistence and routing
remain owned by the existing engine layers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping


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


def discovery_finding(agent: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
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
            findings.append({
                "matches": matches,
                "source": event.get("source") or event.get("provider"),
                "url": event.get("url") or event.get("source_url"),
                "recent": _recent(event),
                "evidence": text[:2000],
            })
    recent_count = sum(item["recent"] for item in findings)
    return {
        "agent": agent,
        "role": "discovery_intelligence",
        "fingerprint": _fingerprint(payload),
        "target": agent.removesuffix("_discovery"),
        "matched_event_count": len(findings),
        "recent_event_count": recent_count,
        "findings": findings,
        "requires_verification": bool(findings),
        "no_match_is_not_rejection": True,
    }


def social_research(agent: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
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
        findings.append({
            "matches": matches,
            "source": event.get("source") or event.get("provider"),
            "url": event.get("url") or event.get("source_url"),
            "recent": is_recent,
            "evidence": text[:2000],
        })
    return {
        "agent": agent,
        "role": "social_research",
        "fingerprint": _fingerprint(payload),
        "matched_event_count": len(findings),
        "recent_event_count": recent,
        "source_count": len(sources),
        "sources": sorted(sources),
        "findings": findings,
        "research_status": "evidence_found" if findings else "research_required",
        "verification_required": True,
        "fabricated_fields": [],
    }


def advanced_handler_registry():
    handlers = {}
    for agent in DISCOVERY_TARGETS:
        handlers[agent] = lambda _agent, payload, _ctx, name=agent: discovery_finding(name, payload)
    for agent in SOCIAL_TARGETS:
        handlers[agent] = lambda _agent, payload, _ctx, name=agent: social_research(name, payload)
    return handlers
