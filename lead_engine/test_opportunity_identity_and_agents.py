from .agent_registry import (
    agent_registry,
    discovery_roles,
    processing_roles,
)
from .lead_identity import lead_identity


def test_same_company_and_person_can_have_distinct_positions():
    first = {
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "AI Engineer",
    }
    second = {
        "source": "linkedin",
        "source_id": "post-2",
        "url": "https://linkedin.example/post-2",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "Data Engineer",
    }

    assert lead_identity(first) != lead_identity(second)


def test_same_source_event_remains_one_opportunity():
    first = {
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "AI Engineer",
        "signal": "Hiring an AI engineer",
    }
    updated_evidence = {
        **first,
        "signal": "Updated hiring details for an AI engineer",
        "evidence": "new evidence",
    }

    assert lead_identity(first) == lead_identity(updated_evidence)


def test_fallback_identity_keeps_distinct_positions_separate():
    first = {
        "company": "Acme",
        "url": "https://acme.example/careers",
        "job_title": "AI Engineer",
        "signal_type": "job",
    }
    second = {
        "company": "Acme",
        "url": "https://acme.example/careers",
        "job_title": "Data Engineer",
        "signal_type": "job",
    }

    assert lead_identity(first) != lead_identity(second)


def test_agent_workforce_is_specialized_and_isolated_by_queue():
    registry = agent_registry()

    assert len(discovery_roles()) >= 9
    assert len(processing_roles()) >= 8
    assert "x_signal" in registry
    assert "paxus_research" in registry
    assert "outreach_closer" in registry
    assert registry["x_signal"].queue.startswith("discovery.")
    assert registry["paxus_research"].queue == "research.paxus"
    assert registry["outreach_closer"].queue == "revenue.outreach"


def test_paxus_research_is_not_the_same_queue_as_discovery_or_outreach():
    registry = agent_registry()

    queues = {
        registry["paxus_research"].queue,
        registry["x_signal"].queue,
        registry["outreach_closer"].queue,
    }

    assert len(queues) == 3
