from datetime import datetime, timedelta, timezone

from .database import LeadDB
from .discovery_gate import apply_discovery_gate
from .pipeline import LeadPipeline


def _now(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _pipeline():
    return LeadPipeline(db=LeadDB(data_dir=":memory:"), sync_enabled=False)


def test_discovery_gate_qualifies_matching_company_without_destroying_other_routes():
    pipeline = _pipeline()
    result = pipeline.process(
        source="test",
        source_id="opp-1",
        url="https://example.test/opp-1",
        company="Acme",
        signal="Acme is hiring a software engineer",
        evidence="Acme is hiring a software engineer now",
        job_title="Software Engineer",
        need_at=_now(),
    )

    gated = apply_discovery_gate(pipeline, result)
    lead = gated["lead"]

    assert gated["qualification_status"] == "qualified"
    assert "Paxus" in lead["qualification_results"]
    assert lead["potential_routes"]
    assert lead["review_state"] == "qualified"


def test_discovery_gate_does_not_mark_old_or_undated_discovery_as_not_qualified():
    pipeline = _pipeline()
    result = pipeline.process(
        source="test",
        source_id="opp-2",
        url="https://example.test/opp-2",
        company="Acme",
        signal="Acme may hire engineers",
        evidence="Old hiring information",
        job_title="Software Engineer",
    )

    gated = apply_discovery_gate(pipeline, result)

    assert gated["qualification_status"] == "unverified"
    assert gated["review_state"] == "review"
    assert gated["lead"]["qualified"] is False


def test_discovery_gate_queues_paxus_research_when_base_qualification_passes():
    pipeline = _pipeline()
    result = pipeline.process(
        source="test",
        source_id="opp-3",
        url="https://example.test/opp-3",
        company="Paxus target",
        signal="Hiring an engineer",
        evidence="Hiring an engineer now",
        job_title="AI Engineer",
        need_at=_now(),
    )

    gated = apply_discovery_gate(pipeline, result)
    lead = gated["lead"]
    paxus = lead["qualification_results"]["Paxus"]

    if paxus["qualified"]:
        assert gated["paxus_qualified"] is True
        assert gated["paxus_true_referral"] is False
        assert gated["paxus_research_status"] == "research_required"
        assert lead["research_status"] == "research_required"
