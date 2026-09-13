import base64
import json

import pytest

from lead_engine.account_auth import (
    AccountAuthConfigurationError,
    SUPPORTED_ACCOUNTS,
    SUPPORTED_OUTREACH_ACCOUNTS,
    authenticated_accounts,
    auth_status,
    configured_accounts,
    credentials_for,
    ensure_authenticated,
    login_credentials,
    playwright_context_options,
    relogin_with_credentials,
)


def test_credentials_are_loaded_only_from_runtime_environment(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_LINKEDIN_USERNAME", "operator@example.test")
    monkeypatch.setenv("THORIO_ACCOUNT_LINKEDIN_PASSWORD", "secret-value")

    credentials = credentials_for("linkedin")

    assert credentials is not None
    assert credentials.username == "operator@example.test"
    assert credentials.password == "secret-value"
    assert configured_accounts() == ("linkedin",)


def test_partial_credentials_fail_closed(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_X_USERNAME", "operator")

    with pytest.raises(AccountAuthConfigurationError, match="both"):
        credentials_for("x")


def test_storage_state_is_decoded_without_logging_secret(monkeypatch):
    state = {"cookies": [{"name": "session", "value": "opaque"}], "origins": []}
    encoded = base64.b64encode(json.dumps(state).encode()).decode()
    monkeypatch.setenv("THORIO_ACCOUNT_THREADS_STORAGE_STATE_B64", encoded)

    options = playwright_context_options("threads")

    assert options == {"storage_state": state}
    assert authenticated_accounts() == ("threads",)


def test_storage_state_must_be_valid_json(monkeypatch):
    encoded = base64.b64encode(b"not-json").decode()
    monkeypatch.setenv("THORIO_ACCOUNT_FACEBOOK_STORAGE_STATE_B64", encoded)

    with pytest.raises(AccountAuthConfigurationError, match="valid base64-encoded JSON"):
        playwright_context_options("facebook")


def test_storage_state_must_have_playwright_state_fields(monkeypatch):
    encoded = base64.b64encode(json.dumps({"unexpected": []}).encode()).decode()
    monkeypatch.setenv("THORIO_ACCOUNT_X_STORAGE_STATE_B64", encoded)

    with pytest.raises(AccountAuthConfigurationError, match="cookies or origins"):
        playwright_context_options("x")


def test_unsupported_accounts_fail_closed():
    with pytest.raises(AccountAuthConfigurationError, match="unsupported account"):
        credentials_for("email")


def test_status_distinguishes_credentials_from_authenticated_session(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_LINKEDIN_USERNAME", "operator")
    monkeypatch.setenv("THORIO_ACCOUNT_LINKEDIN_PASSWORD", "secret")
    state = {"cookies": [], "origins": []}
    encoded = base64.b64encode(json.dumps(state).encode()).decode()
    monkeypatch.setenv("THORIO_ACCOUNT_X_STORAGE_STATE_B64", encoded)

    status = auth_status()

    assert status["linkedin"]["credentials_configured"] is True
    assert status["linkedin"]["session_ready"] is False
    assert status["linkedin"]["relogin_ready"] is True
    assert status["x"]["credentials_configured"] is False
    assert status["x"]["session_ready"] is True
    assert status["x"]["relogin_ready"] is False
    assert status["x"]["secrets_exposed"] is False


def test_relogin_uses_existing_runtime_credentials_without_persisting_them(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_X_USERNAME", "operator")
    monkeypatch.setenv("THORIO_ACCOUNT_X_PASSWORD", "secret")
    received = []

    result = relogin_with_credentials("x", lambda credentials: received.append(credentials))

    assert result is None
    assert received[0].account == "x"
    assert received[0].username == "operator"
    assert received[0].password == "secret"


def test_login_credentials_fail_closed_without_complete_credentials(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_X_USERNAME", "operator")
    with pytest.raises(AccountAuthConfigurationError, match="both"):
        login_credentials("x")


def test_ensure_authenticated_does_not_relogin_when_session_is_valid(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_X_USERNAME", "operator")
    monkeypatch.setenv("THORIO_ACCOUNT_X_PASSWORD", "secret")
    called = []

    result = ensure_authenticated("x", lambda: True, lambda credentials: called.append(credentials))

    assert result is None
    assert called == []


def test_ensure_authenticated_immediately_relogs_in_when_session_is_invalid(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_X_USERNAME", "operator")
    monkeypatch.setenv("THORIO_ACCOUNT_X_PASSWORD", "secret")
    called = []

    ensure_authenticated("x", lambda: False, lambda credentials: called.append(credentials))

    assert len(called) == 1
    assert called[0].account == "x"
    assert called[0].username == "operator"
    assert called[0].password == "secret"


def test_ensure_authenticated_treats_session_check_error_as_logout(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_X_USERNAME", "operator")
    monkeypatch.setenv("THORIO_ACCOUNT_X_PASSWORD", "secret")
    called = []

    def broken_session_check():
        raise RuntimeError("session unavailable")

    ensure_authenticated("x", broken_session_check, lambda credentials: called.append(credentials))

    assert len(called) == 1


def test_gmail_is_supported_only_for_outreach_auth(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", "thorio.partners@gmail.com")
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "runtime-secret")

    credentials = credentials_for("gmail")

    assert credentials is not None
    assert credentials.account == "gmail"
    assert credentials.username == "thorio.partners@gmail.com"
    assert SUPPORTED_OUTREACH_ACCOUNTS == ("gmail",)
    assert "gmail" not in SUPPORTED_ACCOUNTS
    assert "gmail" not in auth_status()
    assert configured_accounts() == ()


def test_only_collection_accounts_remain_in_collection_auth_registry():
    assert SUPPORTED_ACCOUNTS == (
        "linkedin",
        "x",
        "threads",
        "facebook",
        "hacker_news",
        "indie_hackers",
    )
    assert "email" not in SUPPORTED_ACCOUNTS
    assert "gmail" not in SUPPORTED_ACCOUNTS
