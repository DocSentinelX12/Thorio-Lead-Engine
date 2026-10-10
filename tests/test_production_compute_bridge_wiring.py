"""Regression guard for the production-to-free-compute coordinator handoff."""
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-app.yml"


def test_production_engine_receives_the_configured_remote_compute_coordinator():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    engine = workflow.split("\n  engine:\n", 1)[1]
    engine_environment = engine.split("\n    steps:\n", 1)[0]

    assert "THORIO_FREE_ONLY: \"1\"" in engine_environment
    assert (
        "THORIO_COMPUTE_COORDINATOR_URL: ${{ secrets.THORIO_COMPUTE_COORDINATOR_URL }}"
        in engine_environment
    )
    assert (
        "THORIO_COMPUTE_AUTH_TOKEN: ${{ secrets.THORIO_COMPUTE_AUTH_TOKEN }}"
        in engine_environment
    )
    assert 'THORIO_COMPUTE_HTTP_TIMEOUT: "20"' in engine_environment
