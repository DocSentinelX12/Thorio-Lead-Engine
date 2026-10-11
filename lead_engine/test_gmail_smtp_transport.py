import smtplib

import pytest

from .gmail_smtp_transport import EXPECTED_SENDER, GmailSMTPTransport
from .revenue_execution import RevenueTransportUnavailable


class FakeSMTP:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.logged_in = None
        self.sent = []
        self.closed = False

    def ehlo(self):
        return 250, b"ok"

    def starttls(self, context=None):
        return 220, b"ready"

    def login(self, username, password):
        self.logged_in = (username, password)
        if password == "reject":
            raise smtplib.SMTPAuthenticationError(535, b"authentication rejected")

    def send_message(self, message, *, from_addr, to_addrs):
        self.sent.append((message, from_addr, to_addrs))
        return {}

    def quit(self):
        self.closed = True


def test_gmail_smtp_uses_thorio_sender_and_stable_message_id(monkeypatch):
    import smtplib

    fake = FakeSMTP()
    smtp_calls = []
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "test-app-password")
    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: (smtp_calls.append((args, kwargs)) or fake))
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)

    transport = GmailSMTPTransport()
    first = transport.send(
        channel="email",
        recipient={"email": "recruiter@example.test"},
        subject="Hiring question",
        body="Hello, I noticed your current engineering role.",
        idempotency_key="outreach:lead-1:conversation-1:1",
    )
    second = transport.send(
        channel="email",
        recipient={"email": "recruiter@example.test"},
        subject="Hiring question",
        body="Hello, I noticed your current engineering role.",
        idempotency_key="outreach:lead-1:conversation-1:1",
    )

    assert first["status"] == "accepted"
    assert first["sender"] == EXPECTED_SENDER
    assert first["recipient"] == "recruiter@example.test"
    assert first["message_id"] == second["message_id"]
    assert fake.logged_in == (EXPECTED_SENDER, "test-app-password")
    assert smtp_calls[0][0][1] == 587
    assert len(fake.sent) == 2
    assert fake.sent[0][0]["From"] == EXPECTED_SENDER
    assert fake.sent[0][2] == ["recruiter@example.test"]


def test_gmail_smtp_requires_expected_sender_and_password(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", "wrong@example.test")
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "secret")
    with pytest.raises(RevenueTransportUnavailable, match="sender must be"):
        GmailSMTPTransport()

    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_PASSWORD", raising=False)
    with pytest.raises(RevenueTransportUnavailable, match="PASSWORD is required"):
        GmailSMTPTransport()


def test_gmail_smtp_authentication_failure_is_retryable_not_sent(monkeypatch):
    import smtplib

    fake = FakeSMTP()
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "reject")
    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: fake)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)

    transport = GmailSMTPTransport()
    with pytest.raises(RevenueTransportUnavailable, match="authentication failed"):
        transport.send(
            channel="email",
            recipient={"email": "recruiter@example.test"},
            subject="Hiring question",
            body="Hello",
            idempotency_key="outreach:lead-2:conversation-2:1",
        )
    assert fake.sent == []


def test_gmail_smtp_rejects_missing_recipient_before_network(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "test-app-password")
    transport = GmailSMTPTransport()
    with pytest.raises(RevenueTransportUnavailable, match="recipient email"):
        transport.send(
            channel="email",
            recipient={},
            subject="Hiring question",
            body="Hello",
            idempotency_key="outreach:lead-3:conversation-3:1",
        )

def test_runtime_selects_gmail_smtp_from_existing_gmail_credentials(monkeypatch):
    from .revenue_execution import configured_revenue_transport
    from .gmail_smtp_transport import GmailSMTPTransport

    monkeypatch.delenv("THORIO_REVENUE_TRANSPORT_MODE", raising=False)
    monkeypatch.delenv("THORIO_REVENUE_TRANSPORT_URL", raising=False)
    monkeypatch.delenv("THORIO_REVENUE_TRANSPORT_TOKEN", raising=False)
    monkeypatch.delenv("THORIO_REVENUE_BROWSER_TARGETS", raising=False)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "test-app-password")

    assert isinstance(configured_revenue_transport(), GmailSMTPTransport)


def test_explicit_http_mode_does_not_silently_disable_transport(monkeypatch):
    from .revenue_execution import configured_revenue_transport

    monkeypatch.setenv("THORIO_REVENUE_TRANSPORT_MODE", "http")
    monkeypatch.delenv("THORIO_REVENUE_TRANSPORT_URL", raising=False)
    monkeypatch.delenv("THORIO_REVENUE_TRANSPORT_TOKEN", raising=False)
    with pytest.raises(RevenueTransportUnavailable, match="HTTP revenue transport mode requires"):
        configured_revenue_transport()



def test_gmail_smtp_falls_back_to_ssl_when_starttls_connection_disconnects(monkeypatch):
    import smtplib

    fake = FakeSMTP()
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "test-app-password")

    def disconnected(*args, **kwargs):
        raise smtplib.SMTPServerDisconnected("connection closed before greeting")

    monkeypatch.setattr(smtplib, "SMTP", disconnected)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)
    result = GmailSMTPTransport().send(
        channel="email",
        recipient={"email": "recruiter@example.test"},
        subject="Hiring question",
        body="Hello",
        idempotency_key="outreach:lead-fallback:conversation:1",
    )
    assert result["accepted"] is True
    assert fake.sent
