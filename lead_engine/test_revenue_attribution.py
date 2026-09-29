from .database import LeadDB
from .revenue_attribution import revenue_attribution


def _lead(fingerprint, **overrides):
    lead = {
        "fingerprint": fingerprint,
        "opportunity_id": fingerprint,
        "source": "Source A",
        "signal_type": "commercial_intent",
        "qualified": False,
        "research_status": "not_started",
        "sales_eligibility": "blocked",
        "revenue_lifecycle_state": "qualified",
        "signal_matches": [],
    }
    lead.update(overrides)
    return lead


def test_revenue_attribution_groups_source_and_preserves_observed_lifecycle(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead(
        "a",
        qualified=True,
        research_status="complete",
        sales_eligibility="eligible",
        revenue_lifecycle_state="converted",
        response_count=1,
        conversation_id="conversation:a",
        outreach_history=[{"action_id": "outreach-a"}],
        signal_matches=["need ai integration", "looking for a development partner"],
    ))
    db.insert_if_new(_lead(
        "b",
        source="Source B",
        signal_type="hiring",
        qualified=True,
        research_status="complete",
        sales_eligibility="eligible",
        revenue_lifecycle_state="outreach_sent",
        outreach_history=[{"action_id": "outreach-b"}],
    ))
    db.insert_if_new(_lead(
        "c",
        source="Source A",
        signal_type="commercial_intent",
        qualified=False,
        research_status="not_started",
        sales_eligibility="blocked",
        revenue_lifecycle_state="qualified",
    ))

    result = revenue_attribution(db)

    assert result["total_opportunities"] == 3
    source_a = result["by_source"]["Source A"]
    assert source_a["opportunities"] == 2
    assert source_a["qualified"] == 1
    assert source_a["sales_eligible"] == 1
    assert source_a["converted"] == 1
    assert source_a["conversion_rate"] == 0.5
    assert result["by_source"]["Source B"]["opportunities"] == 1
    assert result["by_source"]["Source B"]["outreach_sent"] == 1


def test_revenue_attribution_exact_commercial_triggers_are_multi_attributed(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead(
        "compound",
        qualified=True,
        research_status="complete",
        sales_eligibility="eligible",
        revenue_lifecycle_state="converted",
        signal_matches=["Need AI integration", "Looking for a development partner"],
    ))
    db.insert_if_new(_lead(
        "ai-only",
        qualified=True,
        research_status="complete",
        sales_eligibility="eligible",
        revenue_lifecycle_state="outreach_sent",
        signal_matches=["Need AI integration"],
    ))

    result = revenue_attribution(db)

    ai = result["by_commercial_trigger"]["need ai integration"]
    partner = result["by_commercial_trigger"]["looking for a development partner"]
    assert ai["opportunities"] == 2
    assert ai["converted"] == 1
    assert partner["opportunities"] == 1
    assert partner["converted"] == 1


def test_revenue_attribution_does_not_infer_missing_trigger_matches_from_signal_text(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead(
        "unstructured",
        signal="Need AI integration and development partner",
        signal_matches=[],
    ))

    result = revenue_attribution(db)

    assert result["by_commercial_trigger"] == {}
