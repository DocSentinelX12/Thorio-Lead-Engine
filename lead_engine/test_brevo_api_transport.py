import requests
import pytest

from .brevo_api_transport import BrevoAPITransport, verify_brevo_api_key
from .revenue_execution import RevenueTransportUnavailable


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"email": "account@example.test"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def configure(monkeypatch, **overrides):
    values = {
        "THORIO_BREVO_API_KEY": "brevo-api-key",
        "THORIO_BREVO_SENDER_EMAIL": "support@thorio.co",
        "THORIO_BREVO_SENDER_NAME": "Thorio",
        "THORIO_BREVO_REPLY_TO_EMAIL": "support@thorio.co",
        "THORIO_BREVO_SENDER_VERIFIED": "true",
        "THORIO_BREVO_DOMAIN_AUTHENTICATED": "true",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_brevo_api_key_verification_uses_https_without_sending(monkeypatch):
    calls = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: calls.append((url, kwargs)) or FakeResponse(),
    )
    assert verify_brevo_api_key(api_key="brevo-api-key") is True
    assert len(calls) == 1
    assert calls[0][0] == "https://api.brevo.com/v3/account"
    assert calls[0][1]["headers"]["api-key"] == "brevo-api-key"


def test_brevo_api_transport_sends_verified_message_through_https(monkeypatch):
    configure(monkeypatch)
    calls = []
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs))
        or FakeResponse(payload={"messageId": "<provider-id>"}),
    )
    transport = BrevoAPITransport()
    result = transport.send(
        channel="email",
        recipient={"email": "Hiring Lead <buyer@example.test>"},
        subject="A hiring question",
        body="Would a verified remote hiring lead be useful?",
        idempotency_key="lead:1:conversation:1",
    )
    assert result["provider"] == "brevo_api"
    assert result["accepted"] is True
    assert result["message_id"] == "<provider-id>"
    assert calls[0][0] == "https://api.brevo.com/v3/smtp/email"
    assert calls[0][1]["headers"]["api-key"] == "brevo-api-key"
    assert calls[0][1]["json"]["to"] == [{"email": "buyer@example.test", "name": "Hiring Lead"}]
    assert calls[0][1]["json"]["replyTo"]["email"] == "support@thorio.co"


def test_brevo_api_auth_rejection_never_sends(monkeypatch):
    configure(monkeypatch)
    calls = []
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or FakeResponse(status_code=401, payload={"message": "unauthorized"}),
    )
    transport = BrevoAPITransport()
    with pytest.raises(RevenueTransportUnavailable, match="authorization failed"):
        transport.send(
            channel="email",
            recipient={"email": "buyer@example.test"},
            subject="A hiring question",
            body="Hello",
            idempotency_key="lead:auth-fail",
        )
    assert len(calls) == 1


def test_brevo_api_requires_real_sender_verification(monkeypatch):
    configure(monkeypatch, THORIO_BREVO_SENDER_VERIFIED="false")
    with pytest.raises(RevenueTransportUnavailable, match="sender verification is not confirmed"):
        BrevoAPITransport()



def test_auto_runtime_prefers_brevo_api_when_api_key_is_configured(monkeypatch):
    from . import revenue_execution

    configure(monkeypatch)
    monkeypatch.delenv("THORIO_REVENUE_TRANSPORT_MODE", raising=False)
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", "thorio.partners@gmail.com")
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "existing-gmail-password")
    revenue_execution.register_revenue_transport(None)
    try:
        assert isinstance(revenue_execution.configured_revenue_transport(), BrevoAPITransport)
    finally:
        revenue_execution.register_revenue_transport(None)
