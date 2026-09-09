"""Declarative workforce for the 24/7 lead engine.

Agents are intentionally specialized. Discovery workers collect evidence,
qualification workers review evidence, research workers resolve unknowns,
and revenue workers prepare authorized outreach. The registry does not grant
platform access or bypass provider controls; adapters remain responsible for
permitted access.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class AgentRole:
    name: str
    queue: str
    purpose: str
    max_concurrency: int = 1


DISCOVERY_AGENT_ROLES: Tuple[AgentRole, ...] = (
    AgentRole("x_signal", "discovery.x", "Discover permitted X signals." , 2),
    AgentRole("threads_signal", "discovery.threads", "Discover permitted Threads signals.", 2),
    AgentRole("reddit_signal", "discovery.reddit", "Discover permitted Reddit signals.", 2),
    AgentRole("linkedin_signal", "discovery.linkedin", "Discover permitted LinkedIn signals.", 2),
    AgentRole("facebook_signal", "discovery.facebook", "Discover permitted Facebook signals.", 2),
    AgentRole("instagram_signal", "discovery.instagram", "Discover permitted Instagram signals.", 2),
    AgentRole("hacker_news_signal", "discovery.hacker_news", "Discover Hacker News signals.", 2),
    AgentRole("indie_hackers_signal", "discovery.indie_hackers", "Discover Indie Hackers signals.", 2),
    AgentRole("product_hunt_signal", "discovery.product_hunt", "Discover Product Hunt signals.", 2),
    AgentRole("web_job_signal", "discovery.web_jobs", "Discover web and job-board signals.", 3),
)


PROCESSING_AGENT_ROLES: Tuple[AgentRole, ...] = (
    AgentRole("qualification_a", "qualification.review", "Independent evidence-based qualification review.", 2),
    AgentRole("qualification_b", "qualification.validation", "Independent validation of qualification decisions.", 2),
    AgentRole("company_research", "research.company", "Resolve and enrich company context from permitted sources.", 2),
    AgentRole("paxus_research", "research.paxus", "Research unknown Paxus referral requirements before rejection.", 4),
    AgentRole("duplicate_resolution", "quality.dedupe", "Distinguish duplicate evidence from distinct opportunities.", 1),
    AgentRole("priority", "quality.priority", "Rank opportunities for action.", 1),
    AgentRole("outreach_closer", "revenue.outreach", "Prepare and manage authorized high-value outreach.", 2),
    AgentRole("follow_up", "revenue.follow_up", "Track authorized follow-up and engagement states.", 2),
    AgentRole("monitoring", "system.monitoring", "Detect stalled workers, failures, and queue anomalies.", 1),
    AgentRole("audit", "system.audit", "Audit agent decisions and protected business invariants.", 1),
)


ALL_AGENT_ROLES: Tuple[AgentRole, ...] = (
    DISCOVERY_AGENT_ROLES + PROCESSING_AGENT_ROLES
)


def agent_registry() -> Dict[str, AgentRole]:
    """Return the immutable role definitions keyed by agent name."""
    return {role.name: role for role in ALL_AGENT_ROLES}


def discovery_roles() -> Tuple[AgentRole, ...]:
    return DISCOVERY_AGENT_ROLES


def processing_roles() -> Tuple[AgentRole, ...]:
    return PROCESSING_AGENT_ROLES
