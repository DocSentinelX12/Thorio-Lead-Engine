from .agent_registry import ALL_AGENT_ROLES
from .agent_specializations import get_specialization
from .agent_workers import handler_registry


def test_every_registered_agent_has_a_specialized_handler_and_distinct_queue():
    handlers = handler_registry()
    queues = set()

    assert len(ALL_AGENT_ROLES) == 34
    assert len(handlers) >= len(ALL_AGENT_ROLES)

    for role in ALL_AGENT_ROLES:
        specialization = get_specialization(role.name)
        assert role.name in handlers
        assert callable(handlers[role.name])
        assert specialization.agent == role.name
        assert specialization.mission
        assert specialization.responsibilities
        assert specialization.required_inputs
        assert specialization.outputs
        assert specialization.forbidden_actions
        assert role.queue not in queues
        queues.add(role.queue)


def test_discovery_workers_are_explicitly_non_qualifying():
    handlers = handler_registry()

    for role in ALL_AGENT_ROLES[:15]:
        specialization = get_specialization(role.name)
        assert role.kind == "discovery"
        assert role.name in handlers
        assert any("qualif" in item.lower() for item in specialization.forbidden_actions)


def test_social_research_workers_are_explicitly_evidence_bound():
    handlers = handler_registry()

    for role in ALL_AGENT_ROLES[15:20]:
        specialization = get_specialization(role.name)
        assert role.kind == "social_research"
        assert role.name in handlers
        assert any("fabricat" in item.lower() for item in specialization.forbidden_actions)


def test_processing_workforce_contains_all_required_specialists():
    names = {role.name for role in ALL_AGENT_ROLES}
    assert names == {
        "x_signal", "threads_signal", "reddit_signal", "linkedin_signal", "facebook_signal", "instagram_signal",
        "hacker_news_signal", "indie_hackers_signal", "product_hunt_signal", "web_job_signal",
        "engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery",
        "contract_team_demand_discovery", "recent_inquiry_discovery",
        "social_intelligence", "social_hiring_research", "social_decision_maker_research",
        "social_inquiry_research", "social_company_context",
        "qualification_a", "qualification_b", "company_research", "paxus_research", "identity_resolution",
        "duplicate_resolution", "verification", "priority", "routing", "airtable_integrity", "monitoring",
        "audit", "outreach_closer", "follow_up",
    }
