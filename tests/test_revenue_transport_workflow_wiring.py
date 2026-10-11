"""Guard production wiring for the explicitly configured outbound revenue transport."""

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "python-app.yml"


def test_production_runtime_receives_supported_revenue_transport_configuration():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required_wiring = (
        "THORIO_ACCOUNT_GMAIL_USERNAME: ${{ secrets.THORIO_ACCOUNT_GMAIL_USERNAME }}",
        "THORIO_ACCOUNT_GMAIL_PASSWORD: ${{ secrets.THORIO_ACCOUNT_GMAIL_PASSWORD }}",
        "THORIO_REVENUE_TRANSPORT_MODE:",
        'elif mode == "gmail_smtp":',
        'gmail_ready = gmail_username == "thorio.partners@gmail.com" and gmail_password_configured',
        "THORIO_REVENUE_TRANSPORT_URL:",
        "THORIO_REVENUE_TRANSPORT_TOKEN:",
        "THORIO_REVENUE_BROWSER_TARGETS:",
        "THORIO_REVENUE_BROWSER_INBOUND_TARGETS:",
        "THORIO_BROWSER_PROFILE_DIR:",
        "THORIO_BROWSER_HEADLESS:",
        "THORIO_BROWSER_NAVIGATION_TIMEOUT:",
    )
    for setting in required_wiring:
        assert setting in workflow, f"production revenue transport setting is not wired: {setting}"
