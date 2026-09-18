from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "python-app.yml"


def test_state_recovery_uses_only_successful_completed_production_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--json databaseId,event,status,conclusion' in text
    assert '.status == "completed" and .conclusion == "success"' in text
    assert 'thorio-lead-engine-state' in text


def test_production_gate_preserves_durable_specialist_backlog_but_fails_terminal_work():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'specialist_failed_total > 0' in text
    assert 'SPECIALIST EXECUTION FAILURE:' in text
    assert 'SPECIALIST DRAIN DEFERRED:' in text
    assert 'SPECIALIST DRAIN FAILURE: specialist backlog remained' not in text
