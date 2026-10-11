from email.message import EmailMessage

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

    def login(self, username, password):
        self.logged_in = (username, password)
        if password == "reject":
            raise RuntimeError("authentication rejected")

    def send_message(self, message, *, from_addr, to_addrs):
        self.sent.append((message, from_addr, to_addrs))
        return {}

    def quit(self):
        self.closed = True


def test_gmail_smtp_uses_thorio_sender_and_stable_message_id(monkeypatch):
    import smtplib

    fake = FakeSMTP()
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", EXPECTED_SENDER)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "test-app-password")
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
