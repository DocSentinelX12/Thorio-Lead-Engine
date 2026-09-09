"""Declarative workforce for the 24/7 lead engine.

Execution slots are shared dynamically. Roles describe professional capabilities,
not permanently assigned machines. Discovery and social research are deliberately
scaled more aggressively because they are the largest continuous workloads.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class AgentRole:
    name: str
    queue: str
    purpose: str
    max_concurrency: int = 1
    kind: str = "processing"


DISCOVERY_AGENT_ROLES: Tuple[AgentRole, ...] = (
    AgentRole("x_signal", "discovery.x", "Discover permitted X signals.", 5, "discovery"),
    AgentRole("threads_signal", "discovery.threads", "Discover permitted Threads signals.", 5, "discovery"),
    AgentRole("reddit_signal", "discovery.reddit", "Discover permitted Reddit signals.", 5, "discovery"),
    AgentRole("linkedin_signal", "discovery.linkedin", "Discover permitted LinkedIn signals.", 5, "discovery"),
    AgentRole("facebook_signal", "discovery.facebook", "Discover permitted Facebook signals.", 5, "discovery"),
    AgentRole("instagram_signal", "discovery.instagram", "Discover permitted Instagram signals.", 5, "discovery"),
    AgentRole("hacker_news_signal", "discovery.hacker_news", "Discover Hacker News signals.", 3, "discovery"),
    AgentRole("indie_hackers_signal", "discovery.indie_hackers", "Discover Indie Hackers signals.", 3, "discovery"),
    AgentRole("product_hunt_signal", "discovery.product_hunt", "Discover Product Hunt signals.", 3, "discovery"),
    AgentRole("web_job_signal", "discovery.web_jobs", "Discover web and job-board signals.", 5, "discovery"),
    AgentRole("engineering_demand_discovery", "discovery.engineering_demand", "Find engineering demand signals across collected evidence.", 3, "discovery"),
    AgentRole("ai_demand_discovery", "discovery.ai_demand", "Find AI, ML, data, and automation demand signals.", 3, "discovery"),
    AgentRole("product_design_demand_discovery", "discovery.product_design", "Find product, design, and UX demand signals.", 3, "discovery"),
    AgentRole("contract_team_demand_discovery", "discovery.contract_team", "Find contractor, staff augmentation, outsourcing, and team demand.", 3, "discovery"),
    AgentRole("recent_inquiry_discovery", "discovery.recent_inquiry", "Identify recent explicit inquiries and current buying or hiring needs.", 3, "discovery"),
)

SOCIAL_RESEARCH_AGENT_ROLES: Tuple[AgentRole, ...] = (
    AgentRole("social_intelligence", "research.social_intelligence", "Correlate permitted social evidence for one opportunity.", 3, "social_research"),
    AgentRole("social_hiring_research", "research.social_hiring", "Verify current hiring intent and recency from social evidence.", 3, "social_research"),
    AgentRole("social_decision_maker_research", "research.social_decision_maker", "Resolve decision-maker identity and role from permitted social evidence.", 3, "social_research"),
    AgentRole("social_inquiry_research", "research.social_inquiry", "Investigate recent inquiries and explicit need statements.", 3, "social_research"),
    AgentRole("social_company_context", "research.social_company", "Build company context from permitted social evidence.", 3, "social_research"),
)

PROCESSING_AGENT_ROLES: Tuple[AgentRole, ...] = (
    AgentRole("qualification_a", "qualification.review", "Independent evidence-based qualification review.", 3),
    AgentRole("qualification_b", "qualification.validation", "Independent validation of qualification decisions.", 3),
    AgentRole("company_research", "research.company", "Resolve and enrich company context from permitted sources.", 3),
    AgentRole("paxus_research", "research.paxus", "Research unknown Paxus referral requirements before rejection.", 3),
    AgentRole("identity_resolution", "quality.identity", "Resolve identity before semantic deduplication.", 3),
    AgentRole("duplicate_resolution", "quality.dedupe", "Distinguish duplicate evidence from distinct opportunities.", 3),
    AgentRole("verification", "quality.verification", "Independently verify final evidence and routing prerequisites.", 3),
    AgentRole("priority", "quality.priority", "Rank opportunities for action.", 2),
    AgentRole("routing", "quality.routing", "Route verified opportunities to every valid destination.", 2),
    AgentRole("airtable_integrity", "system.airtable", "Verify durable Airtable synchronization and consistency.", 2),
    AgentRole("monitoring", "system.monitoring", "Detect stalled workers, failures, and queue anomalies.", 2),
    AgentRole("audit", "system.audit", "Audit agent decisions and protected business invariants.", 2),
    AgentRole("outreach_closer", "revenue.outreach", "Prepare human-approved outreach without autonomous sending.", 1),
    AgentRole("follow_up", "revenue.follow_up", "Track human-entered outreach outcomes without autonomous contact.", 1),
)

ALL_AGENT_ROLES: Tuple[AgentRole, ...] = DISCOVERY_AGENT_ROLES + SOCIAL_RESEARCH_AGENT_ROLES + PROCESSING_AGENT_ROLES


def agent_registry() -> Dict[str, AgentRole]:
    return {role.name: role for role in ALL_AGENT_ROLES}


def discovery_roles() -> Tuple[AgentRole, ...]:
    return DISCOVERY_AGENT_ROLES


def social_research_roles() -> Tuple[AgentRole, ...]:
    return SOCIAL_RESEARCH_AGENT_ROLES


def processing_roles() -> Tuple[AgentRole, ...]:
    return PROCESSING_AGENT_ROLES
