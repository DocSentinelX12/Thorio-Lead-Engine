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
        "gmail_credentials_ready = gmail_username == \"thorio.partners@gmail.com\" and bool(gmail_password)",
        "GMAIL SMTP LIVE AUTH",
        'gmail_password = "".join(os.environ.get("THORIO_ACCOUNT_GMAIL_PASSWORD", "").split())',
        "safe_provider_detail(exc)",
        "THORIO_REVENUE_TRANSPORT_URL:",
        "THORIO_REVENUE_TRANSPORT_TOKEN:",
        "THORIO_REVENUE_BROWSER_TARGETS:",
        "THORIO_REVENUE_BROWSER_INBOUND_TARGETS:",
        "THORIO_BROWSER_PROFILE_DIR:",
        "THORIO_BROWSER_HEADLESS:",
        "THORIO_BROWSER_NAVIGATION_TIMEOUT:",
        "GMAIL IMAP LIVE AUTH VERIFIED",
        'stage = "imap_login"',
        'stage = "imap_select"',
    )
    for setting in required_wiring:
        assert setting in workflow, f"production revenue transport setting is not wired: {setting}"


def test_gmail_inbound_readiness_is_independent_of_smtp_connectivity():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    inbound_start = workflow.index("      - name: Report inbound revenue observation readiness")
    inbound_end = workflow.index("      - name: Select and verify Airtable production credential", inbound_start)
    inbound_block = workflow[inbound_start:inbound_end]
    assert "imaplib.IMAP4_SSL" in inbound_block
    assert "smtplib.SMTP" not in inbound_block
    assert "smtp_ready" not in inbound_block
