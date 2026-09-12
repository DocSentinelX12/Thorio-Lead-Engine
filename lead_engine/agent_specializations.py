"""Professional capability contracts for every lead-engine agent.

These contracts are executable guardrails. They describe what each specialist
must produce and what it is forbidden to invent or perform.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class AgentSpecialization:
    agent: str
    mission: str
    responsibilities: Tuple[str, ...]
    required_inputs: Tuple[str, ...]
    outputs: Tuple[str, ...]
    forbidden_actions: Tuple[str, ...]


_SOURCE_ROLES = {
    "x_signal": "X", "threads_signal": "Threads", "reddit_signal": "Reddit",
    "linkedin_signal": "LinkedIn", "facebook_signal": "Facebook", "instagram_signal": "Instagram",
    "hacker_news_signal": "Hacker News", "indie_hackers_signal": "Indie Hackers",
    "product_hunt_signal": "Product Hunt", "web_job_signal": "web and job sources",
}

_DISCOVERY_INTELLIGENCE = {
    "engineering_demand_discovery": "engineering demand",
    "ai_demand_discovery": "AI, ML, data, and automation demand",
    "product_design_demand_discovery": "product, design, and UX demand",
    "contract_team_demand_discovery": "contractor, staff augmentation, outsourcing, and team demand",
    "recent_inquiry_discovery": "recent explicit inquiries and current buying or hiring need",
}

_SOCIAL_ROLES = {
    "social_intelligence": "correlate permitted social evidence across sources",
    "social_hiring_research": "verify current hiring intent and recency from social evidence",
    "social_decision_maker_research": "resolve decision-maker identity and role from permitted social evidence",
    "social_inquiry_research": "investigate recent inquiries and explicit need statements",
    "social_company_context": "build verified company context from social evidence",
}

_SPECIALIZATIONS = []

for agent, source in _SOURCE_ROLES.items():
    _SPECIALIZATIONS.append(AgentSpecialization(
        agent, f"Discover high-value hiring and business-intent signals available through authorized {source} access.",
        ("detect relevant intent", "identify entities", "capture source evidence", "normalize signal metadata"),
        ("source evidence",), ("normalized signals", "evidence references"),
        ("unauthorized access", "credential automation", "qualification decisions", "invented evidence"),
    ))

for agent, target in _DISCOVERY_INTELLIGENCE.items():
    _SPECIALIZATIONS.append(AgentSpecialization(
        agent, f"Discover and consolidate {target} from already collected evidence without fabricating facts.",
        ("scan evidence", "detect target signal", "group related observations", "preserve provenance", "emit research gaps"),
        ("lead or evidence_events",), ("discovery findings", "evidence references", "research requirements"),
        ("invented evidence", "premature qualification", "silent evidence deletion"),
    ))

for agent, mission in _SOCIAL_ROLES.items():
    _SPECIALIZATIONS.append(AgentSpecialization(
        agent, f"Deeply {mission} using only permitted evidence.",
        ("correlate observations", "check recency", "resolve identities", "preserve source provenance", "flag uncertainty"),
        ("lead", "evidence_events"), ("social research", "evidence_events", "research status", "research gaps"),
        ("unauthorized access", "fabricated identity", "fabricated contact", "fabricated consent", "qualification without evidence"),
    ))

_PROCESSING = {
    "qualification_a": ("Perform the primary independent evidence-based qualification review for Thorio, Shiftr, and Paxus.", ("current need", "recent inquiry", "destination categories", "multi-route qualification")),
    "qualification_b": ("Independently validate qualification decisions and challenge unsupported conclusions.", ("recheck evidence", "challenge stale evidence", "verify route logic", "flag disagreement")),
    "company_research": ("Resolve company identity, context, people, products, hiring activity, and evidence.", ("verify company", "research decision makers", "enrich context", "record evidence")),
    "paxus_research": ("Resolve unknown Paxus referral requirements without turning unknown into failure or pass.", ("verify company", "find hiring contact", "verify communication evidence", "verify consent evidence")),
    "identity_resolution": ("Resolve company, person, and opportunity identity before semantic duplicate analysis.", ("compare identity keys", "resolve aliases", "preserve distinct opportunities", "record provenance")),
    "duplicate_resolution": ("Distinguish duplicate evidence from related but distinct opportunities.", ("compare identity", "compare opportunity context", "merge duplicate evidence", "preserve separate needs")),
    "verification": ("Independently verify final evidence and routing prerequisites.", ("recheck critical claims", "check freshness", "check destination gates", "reject unsupported claims")),
    "priority": ("Rank opportunities using verified evidence, qualification, freshness, value, and urgency.", ("score evidence", "explain priority", "respect qualification state", "surface urgent work")),
    "routing": ("Route each verified opportunity to every valid destination without collapsing multi-route matches.", ("evaluate routes", "preserve route evidence", "emit destination set", "block unverified routing")),
    "airtable_integrity": ("Verify durable Airtable synchronization and consistency.", ("check writes", "check identifiers", "detect partial sync", "produce recovery work")),
    "monitoring": ("Continuously detect worker, queue, scheduler, persistence, and delivery anomalies.", ("inspect leases", "detect stalled work", "detect queue growth", "surface failures")),
    "audit": ("Independently audit decisions, provenance, Paxus gates, and protected business invariants.", ("audit qualification", "audit dedupe", "audit routing", "audit provenance")),
    "outreach_closer": ("Autonomously decide, authorize, and execute evidence-grounded revenue outreach actions.", ("understand prospect", "identify problem and buying signal", "select valid destination", "personalize from verified evidence", "handle objections", "choose cadence", "execute authorized outbound", "record conversion state")),
    "follow_up": ("Autonomously advance outreach cadence and conversion tracking from observed outcomes.", ("review engagement", "handle objections", "schedule next step", "record outcomes", "enforce stop states")),
}

for agent, (mission, responsibilities) in _PROCESSING.items():
    forbidden = ("invented evidence", "silent overrides", "unauthorized contact", "provenance deletion", "fabricated urgency", "unsupported promises")
    if agent == "duplicate_resolution":
        forbidden = forbidden + ("merging distinct opportunities",)
    if agent == "monitoring":
        forbidden = forbidden + ("hiding failures",)
    _SPECIALIZATIONS.append(AgentSpecialization(
        agent, mission, responsibilities, ("lead", "evidence_events"),
        ("structured result", "provenance", "research or verification state"),
        forbidden,
    ))

SPECIALIZATIONS: Tuple[AgentSpecialization, ...] = tuple(_SPECIALIZATIONS)


def specialization_registry() -> Dict[str, AgentSpecialization]:
    return {item.agent: item for item in SPECIALIZATIONS}


def get_specialization(agent: str) -> AgentSpecialization:
    try:
        return specialization_registry()[agent]
    except KeyError as exc:
        raise ValueError(f"No professional specialization defined for agent: {agent}") from exc
