import base64
import json

import pytest

from lead_engine.account_auth import (
    AccountAuthConfigurationError,
    SUPPORTED_ACCOUNTS,
    configured_accounts,
    credentials_for,
    playwright_context_options,
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


def test_storage_state_must_be_valid_json(monkeypatch):
    encoded = base64.b64encode(b"not-json").decode()
    monkeypatch.setenv("THORIO_ACCOUNT_FACEBOOK_STORAGE_STATE_B64", encoded)

    with pytest.raises(AccountAuthConfigurationError, match="valid base64-encoded JSON"):
        playwright_context_options("facebook")


def test_only_agreed_accounts_are_supported():
    assert SUPPORTED_ACCOUNTS == (
        "linkedin",
        "x",
        "threads",
        "facebook",
        "hacker_news",
        "indie_hackers",
    )
    assert "email" not in SUPPORTED_ACCOUNTS
