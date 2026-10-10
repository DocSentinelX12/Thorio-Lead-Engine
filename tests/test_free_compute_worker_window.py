"""Regression tests for the bounded scheduled free-compute worker lifecycle."""
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "free-compute-workers.yml"


def test_planned_worker_window_timeout_is_not_reported_as_a_worker_failure():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("- name: Run bounded worker", 1)[1].split("\n      - name:", 1)[0]

    assert "timeout --signal=TERM --kill-after=20s 510s python -m lead_engine.compute_worker" in step
    assert "set +e" in step
    assert "worker_status=$?" in step
    assert 'if [ "$worker_status" -eq 124 ]; then' in step
    assert "WORKER WINDOW COMPLETE" in step
    assert 'exit "$worker_status"' in step
