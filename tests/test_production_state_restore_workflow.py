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

def test_encrypted_state_artifact_is_part_of_persistence_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Upload encrypted state recovery artifact" in workflow
    assert "thorio-lead-engine-state-encrypted" in workflow
    assert "retention-days: 90" in workflow
    assert "STATE_ARTIFACT_UPLOAD_OUTCOME" in workflow
    assert 'STATE_ARTIFACT_UPLOAD_OUTCOME:-skipped}" != "success"' in workflow


def test_encrypted_state_artifact_is_decrypted_before_recovery():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Restore authenticated encrypted state artifact" in workflow
    assert 'lead_engine.github_state restore --data-dir "$candidate_dir/restored" --archive "$candidate_dir/state.enc"' in workflow
    assert 'select(.name == "thorio-lead-engine-state-encrypted" and .expired == false)' in workflow

def test_invalid_cache_falls_back_to_encrypted_artifact_recovery():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    restore = workflow.split("- name: Restore encrypted GitHub Actions state", 1)[1].split(
        "- name: Find newest usable engine state", 1
    )[0]
    assert "STATE CACHE REJECTED" in restore
    assert "attempting verified encrypted artifact recovery instead" in restore
    assert 'printf "restored=false\\n" > .thorio-state-cache/restore.log' in restore


def test_encrypted_recovery_artifact_retention_is_bounded():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    cleanup = workflow.split("- name: Clean up superseded state caches", 1)[1].split(
        "- name: Require durable encrypted state persistence", 1
    )[0]
    assert "CURRENT_ARTIFACT_ID" in cleanup
    assert "thorio-lead-engine-state-encrypted" in cleanup
    assert "Removed superseded encrypted state artifact" in cleanup
    assert "preserving all prior artifacts" in cleanup
