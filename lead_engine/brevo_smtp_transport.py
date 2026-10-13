"""Brevo SMTP relay transport for the authorized Thorio revenue boundary.

This adapter sends only messages already approved by the existing closer
execution boundary. It never logs SMTP credentials or message content.
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


SMTP_HOST = "smtp-relay.brevo.com"
SMTP_PORT = 587
SMTP_SSL_PORT = 465


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def brevo_smtp_configured() -> bool:
    """Return whether all required credentials and explicit sender verification exist."""
    return bool(
        _env("THORIO_BREVO_SMTP_LOGIN")
        and _env("THORIO_BREVO_SMTP_KEY")
        and _env("THORIO_BREVO_SENDER_EMAIL")
        and _env("THORIO_BREVO_SENDER_VERIFIED").lower() in {"1", "true", "yes", "on"}
    )


class BrevoSMTPTransport:
    """Deliver email through Brevo's authenticated SMTP relay."""

    def __init__(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        reply_to_email: str | None = None,
        sender_verified: bool | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.username = (username if username is not None else _env("THORIO_BREVO_SMTP_LOGIN")).strip()
        self.password = (password if password is not None else _env("THORIO_BREVO_SMTP_KEY")).strip()
        self.sender_email = (sender_email if sender_email is not None else _env("THORIO_BREVO_SENDER_EMAIL")).strip()
        self.sender_name = (sender_name if sender_name is not None else _env("THORIO_BREVO_SENDER_NAME") or "Thorio").strip()
        self.reply_to_email = (reply_to_email if reply_to_email is not None else _env("THORIO_BREVO_REPLY_TO_EMAIL") or self.sender_email).strip()
        self.sender_verified = (
            sender_verified if sender_verified is not None
            else _env("THORIO_BREVO_SENDER_VERIFIED").lower() in {"1", "true", "yes", "on"}
        )
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))

        _name, sender_address = parseaddr(self.sender_email)
        _reply_name, reply_address = parseaddr(self.reply_to_email)
        if not self.username or not self.password:
            raise RevenueTransportUnavailable("Brevo SMTP login and SMTP key are required")
        if not sender_address or "@" not in sender_address or sender_address.startswith("@") or sender_address.endswith("@"):
            raise RevenueTransportUnavailable("a valid THORIO_BREVO_SENDER_EMAIL is required")
        if not reply_address or "@" not in reply_address or reply_address.startswith("@") or reply_address.endswith("@"):
            raise RevenueTransportUnavailable("a valid THORIO_BREVO_REPLY_TO_EMAIL is required")
        if not self.sender_verified:
            raise RevenueTransportUnavailable(
                "Brevo sender verification is not confirmed; set THORIO_BREVO_SENDER_VERIFIED=true only after verifying the sender in Brevo"
            )

    @staticmethod
    def _recipient_address(recipient: Mapping[str, Any]) -> str:
        raw = str(recipient.get("email") or recipient.get("address") or "").strip()
        _name, address = parseaddr(raw)
        if not address or "@" not in address or address.startswith("@") or address.endswith("@"):
            raise RevenueTransportUnavailable("a valid recipient email address is required for Brevo SMTP")
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
        if normalized_channel not in {"email", "brevo", "brevo_smtp"}:
            raise RevenueTransportUnavailable(f"Brevo SMTP cannot send channel {normalized_channel!r}")
        address = self._recipient_address(recipient)
        if not str(body or "").strip():
            raise RevenueTransportUnavailable("outbound email body is required")
        if not str(idempotency_key or "").strip():
            raise RevenueTransportUnavailable("stable outbound idempotency key is required")

        message = EmailMessage()
        message["From"] = f"{self.sender_name} <{self.sender_email}>"
        message["To"] = address
        message["Reply-To"] = self.reply_to_email
        message["Subject"] = str(subject or "").strip()
        message["Message-ID"] = self._message_id(str(idempotency_key))
        message["X-Thorio-Idempotency-Key"] = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()
        message.set_content(str(body))

        client = None
        connection_errors: list[tuple[str, Exception]] = []
        for mode, port in (("starttls", SMTP_PORT), ("ssl", SMTP_SSL_PORT)):
            candidate = None
            try:
                if mode == "starttls":
                    candidate = smtplib.SMTP(SMTP_HOST, port, timeout=self.timeout_seconds)
                    candidate.ehlo()
                    candidate.starttls(context=ssl.create_default_context())
                    candidate.ehlo()
                else:
                    candidate = smtplib.SMTP_SSL(
                        SMTP_HOST,
                        port,
                        timeout=self.timeout_seconds,
                        context=ssl.create_default_context(),
                    )
            except Exception as exc:
                connection_errors.append((mode, exc))
                if candidate is not None:
                    try:
                        candidate.quit()
                    except Exception:
                        pass
                continue

            try:
                candidate.login(self.username, self.password)
                client = candidate
                break
            except smtplib.SMTPAuthenticationError as exc:
                try:
                    candidate.quit()
                except Exception:
                    pass
                raise RevenueTransportUnavailable(
                    "Brevo SMTP authentication failed; confirm the SMTP login and SMTP key in Brevo"
                ) from exc
            except (smtplib.SMTPServerDisconnected, OSError, TimeoutError) as exc:
                connection_errors.append((mode, exc))
                try:
                    candidate.quit()
                except Exception:
                    pass
                continue
            except Exception as exc:
                try:
                    candidate.quit()
                except Exception:
                    pass
                raise RevenueTransportUnavailable(
                    "Brevo SMTP authentication failed before message submission"
                ) from exc

        if client is None:
            cause = connection_errors[-1][1] if connection_errors else None
            raise RevenueTransportUnavailable(
                "could not establish Brevo SMTP using STARTTLS port 587 or SSL port 465"
            ) from cause

        try:
            try:
                refused = client.send_message(message, from_addr=self.sender_email, to_addrs=[address])
            except smtplib.SMTPRecipientsRefused as exc:
                raise RevenueTransportUnavailable("Brevo SMTP refused the recipient before accepting the message") from exc
            except Exception as exc:
                # SMTP may have accepted DATA before a disconnect. Do not blindly retry.
                raise RuntimeError("Brevo SMTP send outcome is uncertain; automatic resend is blocked") from exc
            if refused:
                raise RevenueTransportUnavailable("Brevo SMTP did not accept the intended recipient")
            return {
                "provider": "brevo_smtp",
                "status": "accepted",
                "accepted": True,
                "sender": self.sender_email,
                "reply_to": self.reply_to_email,
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
        # SMTP has no idempotency-key lookup API. Uncertain sends are never blindly retried.
        return None
