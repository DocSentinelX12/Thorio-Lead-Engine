"""Regression checks for durable restoration after failed production cycles."""
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-app.yml"


def test_state_selector_preserves_valid_artifacts_from_failed_runs():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split("- name: Find newest usable engine state", 1)[1]
    selector = selector.split("- name: Download previous Lead Engine state", 1)[0]

    assert '.status == "completed"' in selector
    assert '.conclusion == "success" or .conclusion == "failure"' in selector
    assert "thorio-lead-engine-state" in selector
    assert 'gh run download "$run_id"' in selector
    assert "candidate has no non-empty leads.sqlite3" in selector
    assert "PRAGMA integrity_check" in selector
    assert "ENGINE STATE CANDIDATE REJECTED" in selector


def test_restored_database_is_integrity_checked_before_runtime_starts():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation = workflow.split("- name: Validate restored Lead Engine state integrity", 1)[1]
    validation = validation.split("- name: Ensure Lead Engine data directory exists", 1)[0]

    assert "data/leads.sqlite3" in validation
    assert "PRAGMA integrity_check" in validation
    assert "checkpoints" in validation
    assert "refusing to start from an empty database" in validation



def test_missing_engine_state_artifact_after_prior_production_run_fails_closed():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    selector = workflow.split("- name: Find newest usable engine state", 1)[1]
    selector = selector.split("- name: Download previous Lead Engine state", 1)[0]

    assert 'prior_production_run_id=""' in selector
    assert "ENGINE STATE RECOVERY BLOCKED" in selector
    assert 'if [ -z "$previous_run_id" ] && [ -n "$prior_production_run_id" ] && [ "${TURSO_STATE_RESTORED:-false}" != "true" ]; then' in selector
    assert "Refusing to start from an empty database" in selector
    assert "ENGINE STATE BOOTSTRAP" in selector


def test_every_restored_sqlite_database_is_integrity_checked():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation = workflow.split("- name: Validate restored Lead Engine state integrity", 1)[1]
    validation = validation.split("- name: Ensure Lead Engine data directory exists", 1)[0]

    assert 'pathlib.Path("data").rglob("*")' in validation
    assert '{".sqlite", ".sqlite3", ".db"}' in validation
    assert "RESTORED ENGINE STATE INVALID: cannot open SQLite database" in validation
    assert "SQLite integrity_check failed for" in validation

def test_invalid_preflight_run_cannot_publish_empty_state_artifact():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    persistence = workflow.split("- name: Validate Lead Engine state before artifact persistence", 1)[1]
    persistence = persistence.split("- name: Persist Lead Engine state", 1)[0]
    upload = workflow.split("- name: Persist Lead Engine state", 1)[1]

    assert "steps.turso_restore.outcome == 'success'" in persistence
    assert "steps.previous_state.outcome == 'success'" in persistence
    assert "steps.engine_run.outcome != 'skipped'" in persistence
    assert "data/leads.sqlite3 is missing or empty" in persistence
    assert "PRAGMA integrity_check" in persistence
    assert "steps.persist_state_validation.outcome == 'success'" in upload

