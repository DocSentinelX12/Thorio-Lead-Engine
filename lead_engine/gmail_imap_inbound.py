"""Authenticated Gmail IMAP reply observer for Thorio's revenue lifecycle.

Only messages that reference a persisted Thorio outbound Message-ID are
considered replies. The observer never logs message bodies or credentials and
never retries outbound sends. Gmail app-password credentials are read only
from runtime environment variables.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import ssl
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Any, Mapping

from .revenue_conversation import record_inbound_event

EXPECTED_SENDER = "thorio.partners@gmail.com"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


class GmailIMAPUnavailable(RuntimeError):
    """Raised when authenticated Gmail inbound observation is unavailable."""


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def gmail_imap_configured() -> bool:
    return (
        _env("THORIO_ACCOUNT_GMAIL_USERNAME").lower() == EXPECTED_SENDER
        and bool("".join(_env("THORIO_ACCOUNT_GMAIL_PASSWORD").split()))
    )


def _normalize_message_id(value: str) -> str:
    return str(value or "").strip().strip("<>").lower()


def _message_ids(value: str) -> set[str]:
    return {_normalize_message_id(item) for item in re.findall(r"<[^<>]+>", str(value or ""))}


def _outbound_message_index(db: Any, *, limit: int) -> dict[str, dict[str, str]]:
    """Map exact sent Message-IDs to durable lead/conversation identities."""
    index: dict[str, dict[str, str]] = {}
    terminal = {"converted", "referred", "closed_lost", "disqualified", "stopped"}
    for lead in db.all_leads():
        if str(lead.get("revenue_lifecycle_state") or "").strip().lower() in terminal:
            continue
        opportunity_id = str(lead.get("fingerprint") or "").strip()
        conversation_id = str(lead.get("conversation_id") or "").strip()
        history = lead.get("outreach_history")
        if not opportunity_id or not conversation_id or not isinstance(history, list):
            continue
        for item in history:
            if not isinstance(item, Mapping):
                continue
            result = item.get("provider_result")
            if not isinstance(result, Mapping):
                continue
            if result.get("provider") != "gmail_smtp" or result.get("accepted") is not True:
                continue
            message_id = _normalize_message_id(str(result.get("message_id") or ""))
            recipient = parseaddr(str(result.get("recipient") or ""))[1].strip().lower()
            if not message_id or not recipient:
                continue
            index[message_id] = {
                "opportunity_id": opportunity_id,
                "conversation_id": conversation_id,
                "recipient": recipient,
            }
            if len(index) >= max(1, limit):
                return index
    return index


def _reply_body(message: email.message.EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",)) if message.is_multipart() else message
    if part is None or part.get_content_type() != "text/plain":
        return ""
    try:
        body = part.get_content()
    except (LookupError, UnicodeError):
        return ""
    kept: list[str] = []
    for line in str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        lowered = stripped.lower()
        if stripped.startswith(">") or lowered.startswith(("on ", "from:", "sent:", "to:", "subject:")):
            if lowered.startswith("on ") and "wrote:" in lowered:
                break
            if stripped.startswith(">") or lowered.startswith(("from:", "sent:", "to:", "subject:")):
                break
        if "-----original message-----" in lowered:
            break
        kept.append(line)
    return "\n".join(kept).strip()


class GmailIMAPObserver:
    """Observe only inbox messages that reference known outbound Message-IDs."""

    def __init__(self, *, username: str | None = None, password: str | None = None, timeout_seconds: float = 30.0):
        self.username = (username if username is not None else _env("THORIO_ACCOUNT_GMAIL_USERNAME")).strip()
        self.password = "".join((password if password is not None else _env("THORIO_ACCOUNT_GMAIL_PASSWORD")).split())
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))
        if self.username.lower() != EXPECTED_SENDER or not self.password:
            raise GmailIMAPUnavailable("Gmail inbound observation requires the configured Thorio Gmail username and password")

    def observe_replies(self, outbound: Mapping[str, Mapping[str, str]]) -> list[dict[str, str]]:
        if not outbound:
            return []
        client = None
        try:
            client = imaplib.IMAP4_SSL(
                IMAP_HOST,
                IMAP_PORT,
                ssl_context=ssl.create_default_context(),
                timeout=self.timeout_seconds,
            )
            client.login(self.username, self.password)
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise GmailIMAPUnavailable("Gmail IMAP could not select the inbox")
            replies: dict[str, dict[str, str]] = {}
            for original_id in outbound:
                criteria_id = f'"<{original_id}>"'
                status, data = client.search(
                    None, "OR", "HEADER", "In-Reply-To", criteria_id,
                    "HEADER", "References", criteria_id,
                )
                if status != "OK":
                    raise GmailIMAPUnavailable("Gmail IMAP reply-header search failed")
                sequence_ids = (data[0] or b"").split() if data else []
                for sequence_id in sequence_ids:
                    status, fetched = client.fetch(sequence_id, "(RFC822)")
                    if status != "OK":
                        raise GmailIMAPUnavailable("Gmail IMAP could not fetch a matched reply")
                    raw = next(
                        (part[1] for part in fetched if isinstance(part, tuple) and isinstance(part[1], bytes)),
                        None,
                    )
                    if not raw:
                        continue
                    message = BytesParser(policy=policy.default).parsebytes(raw)
                    reply_id = _normalize_message_id(str(message.get("Message-ID") or ""))
                    if not reply_id or reply_id in replies:
                        continue
                    referenced = _message_ids(str(message.get("In-Reply-To") or "") + " " + str(message.get("References") or ""))
                    if _normalize_message_id(original_id) not in referenced:
                        continue
                    sender = parseaddr(str(message.get("From") or ""))[1].strip().lower()
                    if not sender or sender == EXPECTED_SENDER:
                        continue
                    body = _reply_body(message)
                    if not body:
                        continue
                    replies[reply_id] = {
                        "event_id": f"gmail:{reply_id}",
                        "message_id": reply_id,
                        "in_reply_to": _normalize_message_id(original_id),
                        "sender": sender,
                        "body": body,
                    }
            return list(replies.values())
        except GmailIMAPUnavailable:
            raise
        except (OSError, imaplib.IMAP4.error, ssl.SSLError, ValueError) as exc:
            raise GmailIMAPUnavailable("authenticated Gmail IMAP reply observation failed") from exc
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass


def poll_gmail_revenue_inbound(db: Any, *, observer: GmailIMAPObserver | None = None, limit: int = 100) -> dict[str, Any]:
    if observer is None and not gmail_imap_configured():
        return {"status": "disabled", "observer": "gmail_imap", "observed_count": 0, "recorded_count": 0, "failed_count": 0, "failures": [], "observed_message_ids": []}
    try:
        outbound = _outbound_message_index(db, limit=limit)
        observer = observer or GmailIMAPObserver()
        replies = observer.observe_replies(outbound)
        by_message_id = {_normalize_message_id(key): value for key, value in outbound.items()}
        recorded = 0
        for reply in replies:
            original = by_message_id.get(_normalize_message_id(reply.get("in_reply_to", "")))
            if original is None:
                continue
            result = record_inbound_event(
                db,
                opportunity_id=original["opportunity_id"],
                conversation_id=original["conversation_id"],
                event_id=reply["event_id"],
                text=reply["body"],
            )
            recorded += 1 if result else 0
        return {
            "status": "completed", "observer": "gmail_imap",
            "observed_count": len(outbound), "recorded_count": recorded,
            "failed_count": 0, "failures": [],
            "observed_message_ids": list(outbound.keys()),
        }
    except Exception as exc:
        return {
            "status": "failed", "observer": "gmail_imap",
            "observed_count": 0, "recorded_count": 0, "failed_count": 1,
            "failures": [{"observer": "gmail_imap", "error": str(exc)}],
            "observed_message_ids": [],
        }
