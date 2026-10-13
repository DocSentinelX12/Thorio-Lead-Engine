import smtplib

import pytest

from .brevo_smtp_transport import BrevoSMTPTransport, brevo_smtp_configured
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


def configure(monkeypatch, **overrides):
    values = {
        "THORIO_BREVO_SMTP_LOGIN": "smtp-login@example.test",
        "THORIO_BREVO_SMTP_KEY": "smtp-key-value",
        "THORIO_BREVO_SENDER_EMAIL": "support@thorio.co",
        "THORIO_BREVO_SENDER_NAME": "Thorio",
        "THORIO_BREVO_REPLY_TO_EMAIL": "support@thorio.co",
        "THORIO_BREVO_SENDER_VERIFIED": "true",
        "THORIO_BREVO_DOMAIN_AUTHENTICATED": "true",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_brevo_smtp_requires_explicit_sender_verification(monkeypatch):
    configure(monkeypatch, THORIO_BREVO_SENDER_VERIFIED="false")
    assert brevo_smtp_configured() is False
    with pytest.raises(RevenueTransportUnavailable, match="sender verification is not confirmed"):
        BrevoSMTPTransport()


def test_brevo_smtp_requires_domain_authentication(monkeypatch):
    configure(monkeypatch, THORIO_BREVO_DOMAIN_AUTHENTICATED="false")
    assert brevo_smtp_configured() is False
    with pytest.raises(RevenueTransportUnavailable, match="domain authentication is not confirmed"):
        BrevoSMTPTransport()


def test_brevo_smtp_sends_only_after_verified_sender_and_uses_idempotency(monkeypatch):
    configure(monkeypatch)
    import smtplib
    from . import brevo_smtp_transport

    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: fake)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)

    transport = BrevoSMTPTransport()
    result = transport.send(
        channel="email",
        recipient={"email": "buyer@example.test"},
        subject="A hiring question",
        body="Would a verified remote hiring lead be useful?",
        idempotency_key="lead:1:conversation:1",
    )

    assert result["provider"] == "brevo_smtp"
    assert result["accepted"] is True
    assert result["sender"] == "support@thorio.co"
    assert result["reply_to"] == "support@thorio.co"
    assert fake.logged_in == ("smtp-login@example.test", "smtp-key-value")
    assert len(fake.sent) == 1
    message, from_addr, to_addrs = fake.sent[0]
    assert from_addr == "support@thorio.co"
    assert to_addrs == ["buyer@example.test"]
    assert message["X-Thorio-Idempotency-Key"]
    assert message["Reply-To"] == "support@thorio.co"


def test_brevo_smtp_auth_failure_never_submits_message(monkeypatch):
    configure(monkeypatch, THORIO_BREVO_SMTP_KEY="reject")
    import smtplib
    from . import brevo_smtp_transport

    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: fake)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)

    transport = BrevoSMTPTransport()
    with pytest.raises(RevenueTransportUnavailable, match="Brevo SMTP authentication failed"):
        transport.send(
            channel="email",
            recipient={"email": "buyer@example.test"},
            subject="A hiring question",
            body="Hello",
            idempotency_key="lead:auth-fail",
        )
    assert fake.sent == []
