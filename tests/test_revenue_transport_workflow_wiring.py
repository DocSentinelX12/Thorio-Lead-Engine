"""Guard production wiring for the explicitly configured outbound revenue transport."""

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-app.yml"


def test_production_runtime_receives_supported_revenue_transport_configuration():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required_wiring = (
        "THORIO_REVENUE_TRANSPORT_MODE: ${{ secrets.THORIO_REVENUE_TRANSPORT_MODE }}",
        "THORIO_REVENUE_TRANSPORT_URL: ${{ secrets.THORIO_REVENUE_TRANSPORT_URL }}",
        "THORIO_REVENUE_TRANSPORT_TOKEN: ${{ secrets.THORIO_REVENUE_TRANSPORT_TOKEN }}",
        "THORIO_REVENUE_BROWSER_TARGETS: ${{ secrets.THORIO_REVENUE_BROWSER_TARGETS }}",
        "THORIO_BROWSER_PROFILE_DIR: ${{ secrets.THORIO_BROWSER_PROFILE_DIR }}",
        "THORIO_BROWSER_HEADLESS: ${{ secrets.THORIO_BROWSER_HEADLESS }}",
        "THORIO_BROWSER_NAVIGATION_TIMEOUT: ${{ secrets.THORIO_BROWSER_NAVIGATION_TIMEOUT }}",
    )
    for setting in required_wiring:
        assert setting in workflow, f"production revenue transport setting is not wired: {setting}"
