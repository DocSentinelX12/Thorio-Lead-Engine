"""Regression tests for the bounded scheduled free-compute worker lifecycle."""
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "free-compute-workers.yml"


def test_bounded_worker_timeout_requires_registration_and_heartbeat_evidence():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("- name: Run bounded worker and require readiness evidence", 1)[1].split("\n      - name:", 1)[0]

    assert "timeout --signal=TERM --kill-after=20s 510s python -u -m lead_engine.compute_worker" in step
    assert "worker_status=$" + "{PIPESTATUS[0]}" in step
    assert "THORIO_WORKER_REGISTERED worker_id=" in step
    assert "THORIO_WORKER_HEARTBEAT_OK worker_id=" in step
    assert 'if [ "$worker_status" -eq 124 ]; then' in step
    assert "WORKER WINDOW COMPLETE" in step
    assert 'exit "$worker_status"' in step


def test_missing_coordinator_configuration_is_not_reported_as_success():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    gate = workflow.split("- name: Check coordinator configuration and health", 1)[1].split("\n      - name:", 1)[0]
    assert "Free compute worker coordinator URL/token secrets are not configured." in gate
    assert "exit 1" in gate
    assert 'echo "enabled=false"' not in gate


def test_runtime_has_success_markers_for_registration_and_heartbeat():
    source = (WORKFLOW.parents[2] / "lead_engine" / "compute_worker.py").read_text(encoding="utf-8")
    assert 'print(f"THORIO_WORKER_REGISTERED worker_id={client.worker_id}", flush=True)' in source
    assert 'print(f"THORIO_WORKER_HEARTBEAT_OK worker_id={client.worker_id}", flush=True)' in source


def test_worker_window_requires_task_plane_health_and_real_processing_evidence():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "/work/health" in text or "task_plane_ready" in text
    assert "THORIO_WORKER_COORDINATOR_ERROR" in text
    assert "THORIO_WORKER_TASK_FAILED" in text
    assert "THORIO_WORKER_TASK_COMPLETED" in text
    assert "verify_worker_task_processing" in text
    assert "max-parallel: 4" in text
    assert "240s" in text
    assert "THORIO_WORKER_IDLE_SECONDS" in text
    assert "THORIO_WORKER_FABRIC_POLL_SECONDS" in text
