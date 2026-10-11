"""Direct Gmail SMTP transport for the authorized Thorio revenue boundary.

The adapter uses the operator's Gmail app password from runtime secrets, sends
only messages already approved by the existing closer boundary, and never logs
credentials or message content.
"""
from __future__ import annotations

import hashlib
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Mapping

from .revenue_execution import RevenueTransportUnavailable


EXPECTED_SENDER = "thorio.partners@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class GmailSMTPTransport:
    """Deliver email using Gmail's authenticated SSL SMTP endpoint."""

    def __init__(self, *, username: str | None = None, password: str | None = None, timeout_seconds: float = 30.0):
        self.username = (username if username is not None else os.getenv("THORIO_ACCOUNT_GMAIL_USERNAME", "")).strip()
        self.password = (password if password is not None else os.getenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "")).strip()
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))
        if self.username.lower() != EXPECTED_SENDER:
            raise RevenueTransportUnavailable(
                f"Gmail SMTP sender must be the configured Thorio contact address {EXPECTED_SENDER}"
            )
        if not self.password:
            raise RevenueTransportUnavailable("THORIO_ACCOUNT_GMAIL_PASSWORD is required for Gmail SMTP")

    @staticmethod
    def _recipient_address(recipient: Mapping[str, Any]) -> str:
        raw = str(recipient.get("email") or recipient.get("address") or "").strip()
        _name, address = parseaddr(raw)
        if not address or "@" not in address or address.startswith("@") or address.endswith("@"):
            raise RevenueTransportUnavailable("a valid recipient email address is required for Gmail SMTP")
        return address

    @staticmethod
    def _message_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"<{digest}@thorio.co>"

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
        if normalized_channel not in {"email", "gmail", "gmail_smtp"}:
            raise RevenueTransportUnavailable(f"Gmail SMTP cannot send channel {normalized_channel!r}")
        address = self._recipient_address(recipient)
        if not str(body or "").strip():
            raise RevenueTransportUnavailable("outbound email body is required")
        if not str(idempotency_key or "").strip():
            raise RevenueTransportUnavailable("stable outbound idempotency key is required")

        message = EmailMessage()
        message["From"] = EXPECTED_SENDER
        message["To"] = address
        message["Subject"] = str(subject or "").strip()
        message["Message-ID"] = self._message_id(str(idempotency_key))
        message["X-Thorio-Idempotency-Key"] = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()
        message.set_content(str(body))

        try:
            client = smtplib.SMTP_SSL(
                SMTP_HOST,
                SMTP_PORT,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(),
            )
        except Exception as exc:
            raise RevenueTransportUnavailable("could not connect to Gmail's authenticated SMTP endpoint") from exc

        try:
            try:
                client.login(self.username, self.password)
            except Exception as exc:
                raise RevenueTransportUnavailable(
                    "Gmail SMTP authentication failed; verify the stored Gmail credential is an accepted app password"
                ) from exc

            try:
                refused = client.send_message(message, from_addr=EXPECTED_SENDER, to_addrs=[address])
            except smtplib.SMTPRecipientsRefused as exc:
                raise RevenueTransportUnavailable("Gmail SMTP refused the recipient before accepting the message") from exc
            except Exception as exc:
                # A disconnect during message submission can happen after the
                # provider accepted DATA. Keep this outcome uncertain so the
                # durable execution layer will not blindly resend.
                raise RuntimeError("Gmail SMTP send outcome is uncertain; automatic resend is blocked") from exc

            if refused:
                raise RevenueTransportUnavailable("Gmail SMTP did not accept the intended recipient")
            return {
                "provider": "gmail_smtp",
                "status": "accepted",
                "accepted": True,
                "sender": EXPECTED_SENDER,
                "recipient": address,
                "message_id": message["Message-ID"],
                "idempotency_key": str(idempotency_key),
            }
        finally:
            try:
                client.quit()
            except Exception:
                pass

    def reconcile(self, *, idempotency_key: str) -> Mapping[str, Any] | None:
        # SMTP has no idempotency-key lookup API. The durable action ledger
        # handles confirmed sends; uncertain sends are intentionally not retried.
        return None
