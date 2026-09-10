"""Secure runtime access to operator-owned account credentials and browser sessions.

Secrets are supplied by the runtime (for example GitHub Actions secrets), never
stored in source control. Browser storage-state JSON may be supplied as a secret
for an already-authenticated account so a fresh ephemeral worker can create an
authenticated Playwright context without knowing the password.

This module intentionally does not implement platform-specific login bypasses,
CAPTCHA handling, MFA interception, or credential harvesting. Platform adapters
must use only authentication flows the operator is authorized to use.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional


class AccountAuthConfigurationError(RuntimeError):
    """Raised when secure account authentication configuration is invalid."""


@dataclass(frozen=True)
class AccountCredentials:
    """Operator-supplied login material, kept out of logs and persisted data."""

    account: str
    username: str
    password: str

    def as_mapping(self) -> dict[str, str]:
        return {"username": self.username, "password": self.password}


SUPPORTED_ACCOUNTS = (
    "linkedin",
    "x",
    "threads",
    "facebook",
    "hacker_news",
    "indie_hackers",
)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _prefix(account: str) -> str:
    normalized = account.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        raise AccountAuthConfigurationError("account name is required")
    return "THORIO_ACCOUNT_" + normalized.upper()


def credentials_for(account: str) -> Optional[AccountCredentials]:
    """Read a username/password pair from runtime secrets, if both exist."""
    prefix = _prefix(account)
    username = _env(prefix + "_USERNAME")
    password = _env(prefix + "_PASSWORD")
    if not username and not password:
        return None
    if not username or not password:
        raise AccountAuthConfigurationError(
            f"{account}: both {prefix}_USERNAME and {prefix}_PASSWORD are required when credentials are configured"
        )
    return AccountCredentials(account=account, username=username, password=password)


def storage_state_json(account: str) -> Optional[dict[str, Any]]:
    """Decode an authenticated Playwright storage state from a runtime secret.

    Preferred secret format is base64-encoded JSON. Plain JSON is also accepted
    for local development only; production workflows should use base64 secrets.
    """
    prefix = _prefix(account)
    raw = _env(prefix + "_STORAGE_STATE_B64")
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        state = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccountAuthConfigurationError(
            f"{account}: {prefix}_STORAGE_STATE_B64 is not valid base64-encoded JSON"
        ) from exc
    if not isinstance(state, Mapping):
        raise AccountAuthConfigurationError(f"{account}: browser storage state must be a JSON object")
    return dict(state)


def configured_accounts() -> tuple[str, ...]:
    """Return accounts with any configured secure authentication material."""
    configured: list[str] = []
    for account in SUPPORTED_ACCOUNTS:
        prefix = _prefix(account)
        if any(_env(prefix + suffix) for suffix in ("_USERNAME", "_PASSWORD", "_STORAGE_STATE_B64")):
            configured.append(account)
    return tuple(configured)


def auth_status() -> dict[str, dict[str, Any]]:
    """Return non-secret account readiness information suitable for logs."""
    status: dict[str, dict[str, Any]] = {}
    for account in SUPPORTED_ACCOUNTS:
        prefix = _prefix(account)
        username = bool(_env(prefix + "_USERNAME"))
        password = bool(_env(prefix + "_PASSWORD"))
        storage = bool(_env(prefix + "_STORAGE_STATE_B64"))
        status[account] = {
            "configured": username and password or storage,
            "username_configured": username,
            "password_configured": password,
            "storage_state_configured": storage,
            "secrets_exposed": False,
        }
    return status


def playwright_context_options(account: str) -> dict[str, Any]:
    """Return safe Playwright context options for an already-authenticated session."""
    state = storage_state_json(account)
    if state is None:
        raise AccountAuthConfigurationError(
            f"{account}: no storage state is configured; authenticate the account first and export its authorized session"
        )
    return {"storage_state": state}
