"""Professional capability contracts for every lead-engine agent."""

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


SPECIALIZATIONS: Tuple[AgentSpecialization, ...] = (
    AgentSpecialization("x_signal", "Discover high-value hiring and business-intent signals available through authorized X access.", ("detect hiring intent", "identify companies and people", "capture source evidence", "normalize signal metadata"), ("source evidence",), ("normalized signals", "evidence references"), ("unauthorized scraping", "credential automation", "qualification decisions")),
    AgentSpecialization("threads_signal", "Discover relevant hiring and business-intent signals through authorized Threads access.", ("detect intent", "identify entities", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("unauthorized access", "qualification decisions")),
    AgentSpecialization("reddit_signal", "Discover relevant hiring, technology, and business-intent discussions from permitted Reddit access.", ("find relevant discussions", "identify entities", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("unauthorized scraping", "qualification decisions")),
    AgentSpecialization("linkedin_signal", "Discover professional hiring, founder, recruiter, and decision-maker signals through authorized LinkedIn access.", ("detect hiring signals", "identify decision makers", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("unauthorized scraping", "qualification decisions")),
    AgentSpecialization("facebook_signal", "Discover permitted hiring and business-intent signals from Facebook.", ("detect intent", "identify entities", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("unauthorized access", "qualification decisions")),
    AgentSpecialization("instagram_signal", "Discover permitted hiring and business-intent signals from Instagram.", ("detect intent", "identify entities", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("unauthorized access", "qualification decisions")),
    AgentSpecialization("hacker_news_signal", "Discover technology-company and hiring intent from permitted Hacker News data.", ("detect relevant posts", "identify companies", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("qualification decisions", "invented evidence")),
    AgentSpecialization("indie_hackers_signal", "Discover founder, startup, hiring, and business-intent signals from permitted Indie Hackers access.", ("detect relevant discussions", "identify companies", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("qualification decisions", "invented evidence")),
    AgentSpecialization("product_hunt_signal", "Discover product-company and founder signals from permitted Product Hunt access.", ("detect relevant launches", "identify companies", "capture evidence", "normalize signals"), ("source evidence",), ("normalized signals", "evidence references"), ("qualification decisions", "invented evidence")),
    AgentSpecialization("web_job_signal", "Find and validate live technology job opportunities from permitted web and job sources.", ("discover roles", "validate job freshness", "capture application source", "normalize job evidence"), ("source evidence",), ("normalized job opportunities", "evidence references"), ("invented jobs", "unauthorized scraping", "qualification decisions")),
    AgentSpecialization("qualification_a", "Perform the primary independent evidence-based qualification review for Shiftr, Thorio, and Paxus.", ("current need", "evaluate current need evidence", "evaluate recent inquiry", "evaluate company-specific categories", "preserve multi-route qualification", "identify research gaps"), ("lead", "evidence_events"), ("qualification_results", "research requirements", "qualification decision"), ("inventing evidence", "collapsing company routes", "treating unknown as no")),
    AgentSpecialization("qualification_b", "Independently validate qualification decisions and challenge unsupported conclusions.", ("recheck evidence", "challenge stale evidence", "verify route logic", "flag disagreement"), ("lead", "qualification_results", "evidence_events"), ("validation result", "disagreement flags"), ("silently overriding evidence", "inventing evidence")),
    AgentSpecialization("company_research", "Resolve company identity, context, people, products, hiring activity, and evidence from permitted sources.", ("verify company", "research decision makers", "enrich context", "record source evidence"), ("lead",), ("company research", "evidence_events", "research status"), ("fabricating contacts", "fabricating consent")),
    AgentSpecialization("paxus_research", "Resolve unknown Paxus referral requirements without falsely converting unknowns into failures or passes.", ("verify company", "find named hiring contact", "verify communication evidence", "verify consent evidence", "update research state"), ("lead", "paxus qualification"), ("Paxus research result", "true-referral readiness", "research status"), ("fabricating communication", "fabricating consent", "unauthorized contact")),
    AgentSpecialization("duplicate_resolution", "Resolve opportunity identity while preserving distinct positions, people, and needs.", ("compare identity keys", "consolidate duplicate evidence", "preserve distinct opportunities", "record resolution"), ("lead", "candidate evidence"), ("dedupe decision", "evidence merge"), ("merging distinct opportunities", "deleting evidence without provenance")),
    AgentSpecialization("priority", "Rank opportunities using verified evidence, qualification, freshness, value, and urgency.", ("score opportunity", "explain priority", "respect qualification state", "surface urgent work"), ("lead", "qualification_results", "evidence_events"), ("priority score", "priority rationale"), ("inventing urgency", "overriding qualification")),
    AgentSpecialization("outreach_closer", "Prepare and progress authorized revenue outreach for ready opportunities.", ("verify readiness", "prepare personalized outreach", "track engagement", "advance sales state"), ("lead", "authorization", "priority"), ("outreach action", "engagement state"), ("unauthorized outreach", "impersonation", "fabricated consent")),
    AgentSpecialization("follow_up", "Manage authorized follow-up and engagement lifecycle without spamming or bypassing controls.", ("review engagement", "schedule eligible follow-up", "record outcomes", "stop when appropriate"), ("lead", "outreach history", "authorization"), ("follow-up action", "engagement outcome"), ("unauthorized contact", "duplicate outreach", "ignoring opt-outs")),
    AgentSpecialization("monitoring", "Continuously detect worker, queue, scheduler, persistence, and delivery anomalies.", ("inspect leases", "detect stalled work", "detect queue growth", "detect repeated failures", "surface health alerts"), ("queue state", "worker state", "delivery metrics"), ("health findings", "recovery tasks", "alerts"), ("changing business qualification", "hiding failures")),
    AgentSpecialization("audit", "Independently audit agent decisions, evidence provenance, and protected business invariants.", ("audit qualification", "audit dedupe", "audit Paxus gates", "audit state transitions", "audit evidence provenance"), ("lead", "agent outputs", "evidence_events", "state history"), ("audit findings", "violations", "remediation tasks"), ("rewriting provenance", "silently masking violations")),
)


def specialization_registry() -> Dict[str, AgentSpecialization]:
    return {item.agent: item for item in SPECIALIZATIONS}


def get_specialization(agent: str) -> AgentSpecialization:
    try:
        return specialization_registry()[agent]
    except KeyError as exc:
        raise ValueError(f"No professional specialization defined for agent: {agent}") from exc
