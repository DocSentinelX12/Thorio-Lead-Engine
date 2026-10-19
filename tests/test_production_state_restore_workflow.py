"""Regression checks for encrypted GitHub Actions state persistence."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "python-app.yml"


def test_encrypted_cache_is_used_without_external_storage():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/cache/restore@v4" in workflow
    assert "actions/cache/save@v4" in workflow
    assert "lead_engine.github_state restore" in workflow
    assert "lead_engine.github_state snapshot" in workflow
    assert "THORIO_STATE_ENCRYPTION_KEY" in workflow
    assert "THORIO_STATE_S3_ENDPOINT_URL" not in workflow


def test_cache_is_saved_only_after_database_integrity_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation = workflow.index("- name: Validate Lead Engine state before encrypted persistence")
    snapshot = workflow.index("- name: Prepare encrypted state backup")
    save = workflow.index("- name: Save encrypted state to free GitHub Actions cache")
    assert validation < snapshot < save
    assert "PRAGMA integrity_check" in workflow
    assert "DURABLE STATE FAILURE" in workflow


def test_legacy_artifact_recovery_is_retained_until_encrypted_cache_works():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Find newest usable engine state" in workflow
    assert "ENGINE STATE RECOVERY BLOCKED" in workflow
    assert "ENGINE STATE CANDIDATE REJECTED" in workflow
    cleanup = workflow.split("- name: Clean up superseded state caches", 1)[1]
    assert "steps.state_restore.outputs.restored == 'true'" in cleanup

def test_authenticated_cache_skips_expensive_legacy_artifact_history_scan():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    recovery = workflow.split("- name: Find newest usable engine state", 1)[1].split(
        "- name: Stage newer verified artifact over older cached state", 1
    )[0]
    assert "authenticated encrypted cache is authoritative; skipping legacy artifact history scan" in recovery
    assert 'CACHE_STATE_RESTORED_AT:-' in recovery
    assert 'production_runs=""' in recovery
    assert '--limit 1000 --json databaseId,event,status,conclusion' in recovery
