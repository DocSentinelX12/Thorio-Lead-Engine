from .agent_queue import enqueue
from .database import LeadDB
from .production_lifecycle_audit import audit_revenue_lifecycle
from .sales_handoff import package_digest
from .test_sales_eligibility_gate import _lead


def _eligible_lead():
    lead = _lead(qualified=True)
    lead["sales_eligibility"] = "eligible"
    lead["sales_eligibility_reason"] = "eligible"
    return lead


def test_audit_detects_orphaned_eligible_opportunity_without_handoff_or_task(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _eligible_lead()
    db.insert_if_new(lead)
    result = audit_revenue_lifecycle(db.path)
    assert result["sales_eligible_opportunities"] == 1
    assert result["eligible_handoff_mismatch"] == 1
    assert result["orphaned_qualified_opportunities"] == 1
    db.close()


def test_audit_accepts_current_handoff_and_live_closer_task(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _eligible_lead()
    db.insert_if_new(lead)
    db.record_airtable_handoff(
        lead["fingerprint"], package_digest(lead), "recLead", "recResearch",
        ["recCompany"], "2026-10-10T00:00:00+00:00"
    )
    enqueue(db, "outreach_closer", {"lead": lead}, priority=10, dedupe_key=f"sales:{lead['fingerprint']}")
    result = audit_revenue_lifecycle(db.path)
    assert result["eligible_handoff_mismatch"] == 0
    assert result["orphaned_qualified_opportunities"] == 0
    assert result["pending_closer_tasks"] == 1
    db.close()


def test_audit_accepts_durable_sent_action_only_when_lead_state_matches(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _eligible_lead()
    db.insert_if_new(lead)
    db.record_airtable_handoff(
        lead["fingerprint"], package_digest(lead), "recLead", "recResearch",
        ["recCompany"], "2026-10-10T00:00:00+00:00"
    )
    action = {
        "action_id": "action-outreach-1",
        "opportunity_id": lead["fingerprint"],
        "idempotency_key": f"outreach:{lead['fingerprint']}:thorio:1",
        "status": "sent",
        "channel": "email",
    }
    db.set_state("revenue_execution", {"actions": {action["idempotency_key"]: action}})
    db.update_payload(lead["fingerprint"], {"last_outreach_action_id": action["action_id"]})
    result = audit_revenue_lifecycle(db.path)
    assert result["outreach_actions_sent"] == 1
    assert result["opportunities_contacted"] == 1
    assert result["eligible_handoff_mismatch"] == 0
    assert result["orphaned_qualified_opportunities"] == 0
    db.close()


def test_audit_detects_stale_handoff_digest_even_with_live_closer_task(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _eligible_lead()
    db.insert_if_new(lead)
    db.record_airtable_handoff(
        lead["fingerprint"], package_digest(lead), "recLead", "recResearch",
        ["recCompany"], "2026-10-10T00:00:00+00:00"
    )
    changed = dict(lead)
    changed["business_need"] = "a different, newly discovered opportunity"
    db.update_payload(lead["fingerprint"], changed)
    enqueue(db, "outreach_closer", {"lead": changed}, priority=10, dedupe_key=f"sales:{lead['fingerprint']}")
    result = audit_revenue_lifecycle(db.path)
    assert result["eligible_handoff_mismatch"] == 1
    assert result["orphaned_qualified_opportunities"] == 0
    db.close()
