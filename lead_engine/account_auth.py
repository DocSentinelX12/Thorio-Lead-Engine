"""Secure runtime access to operator-owned account credentials and browser sessions.

Secrets are supplied by the runtime, never stored in source control. Browser
storage-state JSON may be supplied for an already-authorized account.

Platform adapters are responsible for normal, authorized authentication flows.
This module deliberately does not bypass CAPTCHA, MFA, rate limits, or other
platform security controls.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional


class AccountAuthConfigurationError(RuntimeError):
    """Raised when secure account authentication configuration is invalid."""


@dataclass(frozen=True)
class AccountCredentials:
    """Operator-supplied login material, kept out of logs and persisted data."""

    account: str
    username: str
    password: str


SUPPORTED_ACCOUNTS = (
    "linkedin",
    "x",
    "threads",
    "facebook",
    "hacker_news",
    "indie_hackers",
)

# Gmail is an outreach channel only. Keep it out of the collection account
# registry so adding Gmail cannot change source discovery or its preflight.
SUPPORTED_OUTREACH_ACCOUNTS = ("gmail",)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _prefix(account: str) -> str:
    normalized = account.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        raise AccountAuthConfigurationError("account name is required")
    if normalized not in SUPPORTED_ACCOUNTS + SUPPORTED_OUTREACH_ACCOUNTS:
        raise AccountAuthConfigurationError(f"unsupported account: {normalized}")
    return "THORIO_ACCOUNT_" + normalized.upper()


def credentials_for(account: str) -> Optional[AccountCredentials]:
    """Read a complete username/password pair from runtime secrets, if present."""
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
    """Decode an authenticated Playwright storage state from a runtime secret."""
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
    if "cookies" not in state and "origins" not in state:
        raise AccountAuthConfigurationError(
            f"{account}: browser storage state must contain cookies or origins"
        )
    return dict(state)


def configured_accounts() -> tuple[str, ...]:
    """Return accounts with any configured secure authentication material."""
    return tuple(
        account
        for account in SUPPORTED_ACCOUNTS
        if any(
            _env(_prefix(account) + suffix)
            for suffix in ("_USERNAME", "_PASSWORD", "_STORAGE_STATE_B64")
        )
    )


def auth_status() -> dict[str, dict[str, Any]]:
    """Return non-secret account readiness information suitable for logs."""
    status: dict[str, dict[str, Any]] = {}
    for account in SUPPORTED_ACCOUNTS:
        prefix = _prefix(account)
        username = bool(_env(prefix + "_USERNAME"))
        password = bool(_env(prefix + "_PASSWORD"))
        storage = bool(_env(prefix + "_STORAGE_STATE_B64"))
        status[account] = {
            "configured": (username and password) or storage,
            "credentials_configured": username and password,
            "username_configured": username,
            "password_configured": password,
            "storage_state_configured": storage,
            "session_ready": storage,
            "relogin_ready": username and password,
            "secrets_exposed": False,
        }
    return status


def authenticated_accounts() -> tuple[str, ...]:
    """Return accounts with a complete authenticated browser session."""
    return tuple(account for account in SUPPORTED_ACCOUNTS if storage_state_json(account) is not None)


def playwright_context_options(account: str) -> dict[str, Any]:
    """Return Playwright context options for an already-authenticated session."""
    state = storage_state_json(account)
    if state is None:
        raise AccountAuthConfigurationError(
            f"{account}: no storage state is configured; authenticate the account first"
        )
    return {"storage_state": state}


def login_credentials(account: str) -> AccountCredentials:
    """Get operator credentials for the platform's normal authorized login flow."""
    credentials = credentials_for(account)
    if credentials is None:
        raise AccountAuthConfigurationError(f"{account}: login credentials are not configured")
    return credentials


def relogin_with_credentials(
    account: str,
    login: Callable[[AccountCredentials], Any],
) -> Any:
    """Immediately invoke the authorized platform login adapter with stored credentials.

    The callback receives credentials only in memory. They are never logged,
    serialized, returned in status, or persisted by this module. The adapter
    must implement the platform's ordinary login flow and handle any required
    user verification normally.
    """
    return login(login_credentials(account))


def ensure_authenticated(
    account: str,
    session_is_valid: Callable[[], bool],
    login: Callable[[AccountCredentials], Any],
) -> Any:
    """Use the existing session when valid, otherwise immediately relog in.

    A platform adapter calls this before authenticated work and after an
    authentication failure/logout signal. If the current session is valid,
    no credentials are touched. If it is not valid, the already-configured
    credentials are supplied to the normal authorized login adapter.
    """
    try:
        if session_is_valid():
            return None
    except Exception:
        # Treat an authentication/session-check failure as a logged-out state.
        pass
    return relogin_with_credentials(account, login)
