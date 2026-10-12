from __future__ import annotations

import pytest
import requests

from . import gmail_oauth


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"access_token": "access-token", "expires_in": 3600}

    def json(self):
        return self._payload


def test_gmail_oauth_requires_all_three_secrets(monkeypatch):
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("THORIO_GMAIL_OAUTH_REFRESH_TOKEN", raising=False)
    assert gmail_oauth.gmail_oauth_configured() is False
    with pytest.raises(gmail_oauth.GmailOAuthUnavailable, match="REFRESH_TOKEN"):
        gmail_oauth.refresh_gmail_access_token()


def test_gmail_oauth_refreshes_access_token_without_logging_secrets(monkeypatch):
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_REFRESH_TOKEN", "refresh-token")
    calls = []

    def fake_post(url, *, data, timeout):
        calls.append((url, data, timeout))
        return FakeResponse()

    monkeypatch.setattr(gmail_oauth.requests, "post", fake_post)
    assert gmail_oauth.refresh_gmail_access_token() == "access-token"
    assert calls[0][0] == gmail_oauth.TOKEN_URL
    assert calls[0][1]["refresh_token"] == "refresh-token"
    assert calls[0][1]["grant_type"] == "refresh_token"


def test_gmail_oauth_rejection_does_not_echo_response_body(monkeypatch):
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setattr(gmail_oauth.requests, "post", lambda *a, **k: FakeResponse(401, {"error": "invalid_grant", "refresh_token": "do-not-log"}))
    with pytest.raises(gmail_oauth.GmailOAuthUnavailable, match="HTTP 401") as error:
        gmail_oauth.refresh_gmail_access_token()
    assert "do-not-log" not in str(error.value)


def test_xoauth2_payload_uses_control_a_delimiters():
    assert gmail_oauth.xoauth2_payload("user@gmail.com", "token") == (
        b"user=user@gmail.com\x01auth=Bearer token\x01\x01"
    )
