from .database import LeadDB
from .revenue_metrics import collect_revenue_metrics


def test_revenue_metrics_separate_sales_execution_from_airtable_sync(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new({
        "fingerprint": "metric-1",
        "company": "Acme",
        "qualified": True,
        "research_status": "complete",
        "sales_eligibility": "eligible",
        "revenue_lifecycle_state": "outreach_sent",
        "conversation_id": "conversation:metric-1:thorio",
        "outreach_history": [{"action_id": "a1"}],
    })
    db.insert_if_new({
        "fingerprint": "metric-2",
        "company": "Beta",
        "qualified": True,
        "research_status": "complete",
        "sales_eligibility": "blocked",
        "sales_eligibility_reason": "missing_contact_email",
        "revenue_lifecycle_state": "qualified",
    })
    metrics = collect_revenue_metrics(db)
    assert metrics["discovered"] == 2
    assert metrics["researched"] == 2
    assert metrics["qualified"] == 2
    assert metrics["sales_eligible"] == 1
    assert metrics["outreach_sent"] == 0
    assert metrics["orphaned_qualified"] == 0


def test_revenue_metrics_expose_source_and_signal_attribution(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new({
        "fingerprint": "metric-attribution-1",
        "opportunity_id": "metric-attribution-1",
        "source": "Source A",
        "signal_type": "commercial_intent",
        "signal_matches": ["need ai integration"],
        "qualified": True,
        "research_status": "complete",
        "sales_eligibility": "eligible",
        "revenue_lifecycle_state": "converted",
        "response_count": 1,
        "conversation_id": "conversation:metric-attribution-1",
        "outreach_history": [{"action_id": "a1"}],
    })
    metrics = collect_revenue_metrics(db)
    attribution = metrics["attribution"]
    assert attribution["total_opportunities"] == 1
    assert attribution["by_source"]["Source A"]["converted"] == 1
    assert attribution["by_signal_type"]["commercial_intent"]["sales_eligible"] == 1
    assert attribution["by_commercial_trigger"]["need ai integration"]["converted"] == 1
