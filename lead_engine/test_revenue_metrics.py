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
