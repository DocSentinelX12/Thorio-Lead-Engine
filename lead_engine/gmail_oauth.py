"""OAuth 2.0 XOAUTH2 support shared by Gmail SMTP and IMAP transports.

Only the refresh-token exchange is performed here. Tokens and credentials are
never logged. The Google refresh token must be authorized for the Gmail
mail.google.com scope so it can be used by both SMTP and IMAP.
"""
from __future__ import annotations

import os
from typing import Any

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailOAuthUnavailable(RuntimeError):
    """Raised when Gmail OAuth credentials cannot obtain an access token."""


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def gmail_oauth_configured() -> bool:
    return all(
        _env(name)
        for name in (
            "THORIO_GMAIL_OAUTH_CLIENT_ID",
            "THORIO_GMAIL_OAUTH_CLIENT_SECRET",
            "THORIO_GMAIL_OAUTH_REFRESH_TOKEN",
        )
    )


def refresh_gmail_access_token(*, timeout_seconds: float = 15.0) -> str:
    """Exchange the configured refresh token for a short-lived access token."""
    client_id = _env("THORIO_GMAIL_OAUTH_CLIENT_ID")
    client_secret = _env("THORIO_GMAIL_OAUTH_CLIENT_SECRET")
    refresh_token = _env("THORIO_GMAIL_OAUTH_REFRESH_TOKEN")
    if not all((client_id, client_secret, refresh_token)):
        raise GmailOAuthUnavailable(
            "Gmail OAuth requires THORIO_GMAIL_OAUTH_CLIENT_ID, "
            "THORIO_GMAIL_OAUTH_CLIENT_SECRET, and THORIO_GMAIL_OAUTH_REFRESH_TOKEN"
        )
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=max(5.0, min(float(timeout_seconds), 60.0)),
        )
    except requests.RequestException as exc:
        raise GmailOAuthUnavailable(
            f"Gmail OAuth token endpoint is unreachable ({type(exc).__name__})"
        ) from exc
    if response.status_code != 200:
        # Never include the response body: OAuth errors can echo sensitive
        # account or client details and the access token must remain private.
        raise GmailOAuthUnavailable(
            f"Gmail OAuth refresh was rejected (HTTP {response.status_code})"
        )
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise GmailOAuthUnavailable("Gmail OAuth returned invalid JSON") from exc
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise GmailOAuthUnavailable("Gmail OAuth response did not include an access token")
    return token.strip()


def xoauth2_payload(username: str, access_token: str) -> bytes:
    """Return the raw SASL XOAUTH2 response; protocol clients base64-encode it."""
    user = str(username or "").strip()
    token = str(access_token or "").strip()
    if not user or not token:
        raise GmailOAuthUnavailable("Gmail XOAUTH2 requires a username and access token")
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
