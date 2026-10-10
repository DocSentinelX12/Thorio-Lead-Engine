"""Guard bounded restoration of encrypted browser state in production runs."""
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-app.yml"


def test_browser_state_restore_reuses_selected_state_run_before_bounded_fallback():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    restore = workflow.split("- name: Restore encrypted external browser authentication state", 1)[1]
    restore = restore.split("- name: Start external headless browser", 1)[0]

    assert "THORIO_PREVIOUS_STATE_RUN_ID: ${{ steps.previous_state.outputs.run_id }}" in restore
    assert 'previous_run_id="${THORIO_PREVIOUS_STATE_RUN_ID:-}"' in restore
    assert "--limit 50" in restore
    assert "--limit 1000" not in restore
    assert "bounded fallback checked" in restore
