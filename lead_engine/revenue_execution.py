"""Privileged, durable boundary between the sales closer and outbound transports.

The closer never receives provider credentials and never calls a provider directly.
A transport implementation is injected by the runtime. Every action receives a
stable idempotency key and is persisted before/after transport execution so a
crash can be reconciled without blindly sending the same message twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import uuid4

STATE_KEY = "revenue_execution"
PRIVILEGED_CAPABILITY = "high_ticket_sales_closer"


class RevenueExecutionError(RuntimeError):
    """Base error for revenue execution."""


class RevenueAuthorizationError(RevenueExecutionError):
    """Raised when a non-privileged worker attempts outbound execution."""


class RevenueTransportUnavailable(RevenueExecutionError):
    """Raised when no authorized outbound transport is configured."""


class RevenueTransport(Protocol):
    def send(self, *, channel: str, recipient: Mapping[str, Any], subject: str, body: str, idempotency_key: str) -> Mapping[str, Any]:
        """Send one authorized message and return a provider result."""


@dataclass(frozen=True)
class RevenueAction:
    action_id: str
    opportunity_id: str
    conversation_id: str
    idempotency_key: str
    channel: str
    status: str
    provider_result: Mapping[str, Any] | None = None
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(db) -> dict[str, Any]:
    state = db.get_state(STATE_KEY)
    if not isinstance(state, dict):
        return {"actions": {}}
    actions = state.get("actions")
    return {"actions": actions if isinstance(actions, dict) else {}}


def _save(db, state: dict[str, Any]) -> None:
    db.set_state(STATE_KEY, state)


def _authorized(worker_capability: str) -> None:
    if worker_capability != PRIVILEGED_CAPABILITY:
        raise RevenueAuthorizationError("outbound sales transport requires the privileged high-ticket closer capability")


def execute_outbound(
    db: Any,
    *,
    worker_capability: str,
    opportunity_id: str,
    conversation_id: str,
    channel: str,
    recipient: Mapping[str, Any],
    subject: str,
    body: str,
    transport: RevenueTransport | None,
    idempotency_key: str | None = None,
) -> RevenueAction:
    """Execute one outbound action with durable idempotency.

    The durable action is written before transport execution. A completed
    provider result is authoritative on retry. An action left in ``sending``
    after a crash must be reconciled by the transport using the same
    idempotency key rather than issuing a new key.
    """
    _authorized(worker_capability)
    opportunity_id = str(opportunity_id or "").strip()
    conversation_id = str(conversation_id or "").strip()
    channel = str(channel or "").strip().lower()
    if not opportunity_id or not conversation_id or not channel:
        raise RevenueExecutionError("opportunity_id, conversation_id, and channel are required")
    if not str(body or "").strip():
        raise RevenueExecutionError("outbound body is required")
    if not isinstance(recipient, Mapping) or not recipient:
        raise RevenueExecutionError("recipient is required")
    if transport is None:
        raise RevenueTransportUnavailable("no authorized revenue transport is configured")

    idem = str(idempotency_key or "").strip() or f"revenue:{opportunity_id}:{conversation_id}:{channel}"
    state = _load(db)
    actions = state["actions"]
    existing = actions.get(idem)
    if isinstance(existing, Mapping):
        status = str(existing.get("status") or "")
        if status == "sent":
            return RevenueAction(
                action_id=str(existing["action_id"]), opportunity_id=opportunity_id,
                conversation_id=conversation_id, idempotency_key=idem, channel=channel,
                status="sent", provider_result=existing.get("provider_result"), error=None,
            )

    action_id = str(existing.get("action_id")) if isinstance(existing, Mapping) and existing.get("action_id") else uuid4().hex
    actions[idem] = {
        "action_id": action_id,
        "opportunity_id": opportunity_id,
        "conversation_id": conversation_id,
        "idempotency_key": idem,
        "channel": channel,
        "status": "sending",
        "created_at": str(existing.get("created_at")) if isinstance(existing, Mapping) else _now(),
        "updated_at": _now(),
    }
    _save(db, state)

    try:
        provider_result = dict(transport.send(
            channel=channel,
            recipient=dict(recipient),
            subject=str(subject or ""),
            body=str(body),
            idempotency_key=idem,
        ))
    except Exception as exc:
        state = _load(db)
        state["actions"][idem] = {
            **state["actions"].get(idem, {}),
            "status": "retryable",
            "error": str(exc)[:4000],
            "updated_at": _now(),
        }
        _save(db, state)
        raise

    state = _load(db)
    state["actions"][idem] = {
        **state["actions"].get(idem, {}),
        "status": "sent",
        "provider_result": provider_result,
        "updated_at": _now(),
    }
    _save(db, state)
    action = state["actions"][idem]
    return RevenueAction(
        action_id=action_id,
        opportunity_id=opportunity_id,
        conversation_id=conversation_id,
        idempotency_key=idem,
        channel=channel,
        status="sent",
        provider_result=provider_result,
    )
