"""Regression checks for durable S3 state recovery in production workflow."""
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
    assert "S3_STATE_RESTORED" in selector


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
    assert '!= "true"' in selector
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


def test_s3_persistence_is_required_and_bounded():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    restore = workflow.split("- name: Restore durable S3 engine state", 1)[1]
    restore = restore.split("- name: Find newest usable engine state", 1)[0]
    snapshot = workflow.split("- name: Persist durable S3 engine state", 1)[1]
    snapshot = snapshot.split("- name: Verify active collection and Airtable delivery", 1)[0]
    artifact_upload = workflow.split("- name: Persist Lead Engine state", 1)[1]
    final_gate = workflow.split("- name: Require durable S3 persistence", 1)[1]

    assert "python -m lead_engine.s3_state restore --data-dir data" in restore
    assert "S3 STATE RESTORE FAILURE" in restore
    assert "id: s3_snapshot" in snapshot
    assert "timeout-minutes: 10" in snapshot
    assert "continue-on-error: true" in snapshot
    assert "timeout --signal=TERM --kill-after=5s 540s python -u -m lead_engine.s3_state snapshot --data-dir data" in snapshot
    assert "S3 STATE SNAPSHOT DEADLINE" in snapshot
    assert "name: thorio-lead-engine-state" in artifact_upload
    assert "retention-days: 90" in artifact_upload
    assert "S3_SNAPSHOT_OUTCOME" in final_gate
    assert '!= "success"' in final_gate
    assert "S3 generation objects, checksums, manifest, and latest-generation pointer" in final_gate
    assert "TURSO_" not in workflow
    assert "turso_state" not in workflow


def test_s3_credentials_are_checked_before_expensive_runtime_setup():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    check = workflow.split("- name: Validate durable S3 state storage configuration", 1)[1]
    check = check.split("- name: Install dependencies", 1)[0]
    for name in (
        "THORIO_STATE_S3_ENDPOINT_URL",
        "THORIO_STATE_S3_BUCKET",
        "THORIO_STATE_S3_ACCESS_KEY_ID",
        "THORIO_STATE_S3_SECRET_ACCESS_KEY",
    ):
        assert name in check
    assert "DURABLE STATE CONFIGURATION BLOCKED" in check
