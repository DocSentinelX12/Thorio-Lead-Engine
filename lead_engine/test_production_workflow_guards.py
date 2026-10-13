from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "python-app.yml"


def test_state_recovery_uses_only_successful_completed_production_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--json databaseId,event,status,conclusion' in text
    assert '.status == "completed" and .conclusion == "success"' in text
    assert '--limit 1000 --json databaseId,event,status,conclusion' in text
    assert 'thorio-lead-engine-state' in text


def test_production_gate_preserves_durable_specialist_backlog_but_fails_terminal_work():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'specialist_failed_total > 0' in text
    assert 'SPECIALIST EXECUTION FAILURE:' in text
    assert 'SPECIALIST DRAIN DEFERRED:' in text
    assert 'SPECIALIST DRAIN FAILURE: specialist backlog remained' not in text


def test_airtable_capacity_blocks_new_records_without_discarding_local_collection_state():
    text = WORKFLOW.read_text(encoding="utf-8")
    capacity_gate = text.split("if capacity_blocked:", 1)[1].split("raise SystemExit(", 1)[0]
    assert 'AIRTABLE_SYNC_BLOCK_REASON=record_capacity' in capacity_gate
    assert 'LEAD_ENGINE_SYNC_ENABLED=false' not in capacity_gate
    assert 'AIRTABLE_READ_ONLY_MODE=true' not in capacity_gate
    assert 'updates to known existing records may continue' in capacity_gate
    assert 'AIRTABLE DELIVERY BLOCKED: the base record limit prevented synchronization.' in text
    assert 'Local SQLite state and the pending backlog will be persisted for recovery' in text
