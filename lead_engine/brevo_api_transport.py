"""Brevo HTTPS API transport for authorized Thorio revenue messages.

Uses a Brevo API key over HTTPS, avoiding SMTP port availability and SMTP-login
credential ambiguity. It only sends messages approved by the existing closer
execution boundary and never logs credentials or message bodies.
"""
from __future__ import annotations

import hashlib
import os
from email.utils import parseaddr
from typing import Any, Mapping

import requests

from .revenue_execution import RevenueTransportUnavailable

API_BASE = "https://api.brevo.com/v3"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def brevo_api_key_configured() -> bool:
    return bool(_env("THORIO_BREVO_API_KEY"))


def verify_brevo_api_key(*, api_key: str | None = None, timeout_seconds: float = 15.0) -> bool:
    """Verify the API key against Brevo without sending a message."""
    key = (api_key if api_key is not None else _env("THORIO_BREVO_API_KEY")).strip()
    if not key:
        return False
    response = requests.get(
        f"{API_BASE}/account",
        headers={"api-key": key, "accept": "application/json"},
        timeout=max(3.0, min(float(timeout_seconds), 30.0)),
    )
    if response.status_code in {401, 403}:
        return False
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping) or not payload.get("email"):
        raise RevenueTransportUnavailable("Brevo API returned an unexpected account response")
    return True


class BrevoAPITransport:
    """Deliver email through Brevo's HTTPS transactional email API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        reply_to_email: str | None = None,
        sender_verified: bool | None = None,
        domain_authenticated: bool | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = (api_key if api_key is not None else _env("THORIO_BREVO_API_KEY")).strip()
        self.sender_email = (sender_email if sender_email is not None else _env("THORIO_BREVO_SENDER_EMAIL")).strip()
        self.sender_name = (sender_name if sender_name is not None else _env("THORIO_BREVO_SENDER_NAME") or "Thorio").strip()
        self.reply_to_email = (reply_to_email if reply_to_email is not None else _env("THORIO_BREVO_REPLY_TO_EMAIL") or self.sender_email).strip()
        self.sender_verified = (
            sender_verified if sender_verified is not None
            else _env("THORIO_BREVO_SENDER_VERIFIED").lower() in {"1", "true", "yes", "on"}
        )
        self.domain_authenticated = (
            domain_authenticated if domain_authenticated is not None
            else _env("THORIO_BREVO_DOMAIN_AUTHENTICATED").lower() in {"1", "true", "yes", "on"}
        )
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))

        _name, sender = parseaddr(self.sender_email)
        _reply_name, reply_to = parseaddr(self.reply_to_email)
        if not self.api_key:
            raise RevenueTransportUnavailable("THORIO_BREVO_API_KEY is required")
        if not sender or "@" not in sender:
            raise RevenueTransportUnavailable("a valid THORIO_BREVO_SENDER_EMAIL is required")
        if not reply_to or "@" not in reply_to:
            raise RevenueTransportUnavailable("a valid THORIO_BREVO_REPLY_TO_EMAIL is required")
        if not self.sender_verified:
            raise RevenueTransportUnavailable("Brevo sender verification is not confirmed")
        if not self.domain_authenticated:
            raise RevenueTransportUnavailable("Brevo sender domain authentication is not confirmed")

    @staticmethod
    def _recipient(recipient: Mapping[str, Any]) -> dict[str, str]:
        raw = str(recipient.get("email") or recipient.get("address") or "").strip()
        name, address = parseaddr(raw)
        if not address or "@" not in address:
            raise RevenueTransportUnavailable("a valid recipient email address is required for Brevo API")
        result = {"email": address}
        if name:
            result["name"] = name
        return result

    def send(
        self,
        *,
        channel: str,
        recipient: Mapping[str, Any],
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        normalized_channel = str(channel or "").strip().lower()
        if normalized_channel not in {"email", "brevo", "brevo_api"}:
            raise RevenueTransportUnavailable(f"Brevo API cannot send channel {normalized_channel!r}")
        if not str(body or "").strip():
            raise RevenueTransportUnavailable("outbound email body is required")
        key = str(idempotency_key or "").strip()
        if not key:
            raise RevenueTransportUnavailable("stable outbound idempotency key is required")

        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        payload = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [self._recipient(recipient)],
            "replyTo": {"email": self.reply_to_email},
            "subject": str(subject or "").strip(),
            "textContent": str(body),
            "headers": {
                "X-Thorio-Idempotency-Key": digest,
                "X-Thorio-Conversation-Key": digest,
            },
        }
        try:
            response = requests.post(
                f"{API_BASE}/smtp/email",
                headers={"api-key": self.api_key, "accept": "application/json", "content-type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            # The provider outcome can be uncertain; the execution boundary must not blindly retry.
            raise RuntimeError("Brevo API send outcome is uncertain; automatic resend is blocked") from exc
        if response.status_code in {401, 403}:
            raise RevenueTransportUnavailable("Brevo API authorization failed before message acceptance")
        if response.status_code >= 500:
            raise RuntimeError("Brevo API send outcome may be uncertain; automatic resend is blocked")
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, Mapping) or not str(result.get("messageId") or "").strip():
            raise RuntimeError("Brevo API response did not confirm message acceptance")
        return {
            "provider": "brevo_api",
            "status": "accepted",
            "accepted": True,
            "sender": self.sender_email,
            "reply_to": self.reply_to_email,
            "recipient": self._recipient(recipient)["email"],
            "message_id": str(result["messageId"]),
            "idempotency_key": key,
        }

    def reconcile(self, *, idempotency_key: str) -> Mapping[str, Any] | None:
        # Brevo's send endpoint does not expose a reliable idempotency lookup.
        # Never resend automatically after an uncertain result.
        return None
