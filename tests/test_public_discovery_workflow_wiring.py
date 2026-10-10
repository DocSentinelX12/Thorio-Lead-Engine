"""Protect production wiring for the public business-intent discovery lanes."""

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-app.yml"
LANES = (
    "X_SIGNAL",
    "THREADS_SIGNAL",
    "REDDIT_SIGNAL",
    "LINKEDIN_SIGNAL",
    "FACEBOOK_SIGNAL",
    "INSTAGRAM_SIGNAL",
    "HACKER_NEWS_SIGNAL",
    "INDIE_HACKERS_SIGNAL",
    "PRODUCT_HUNT_SIGNAL",
    "WEB_JOB_SIGNAL",
)


def test_production_runtime_receives_each_discovery_lane_configuration():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "THORIO_BROWSER_DISCOVERY_TARGETS: ${{ secrets.THORIO_BROWSER_DISCOVERY_TARGETS }}" in workflow
    for lane in LANES:
        prefix = f"THORIO_DISCOVERY_{lane}_"
        for field in ("ENABLED", "URL", "TOKEN", "RECORDS_PATH", "TEXT_FIELDS", "COMPANY_FIELDS", "PERSON_FIELDS"):
            assert f"{prefix}{field}:" in workflow, f"production discovery setting is not wired: {prefix}{field}"


def test_production_runtime_reports_missing_public_discovery_without_exposing_secrets():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Report public discovery source readiness" in workflow
    assert "PUBLIC DISCOVERY READINESS:" in workflow
    assert "PUBLIC DISCOVERY BLOCKER:" in workflow
