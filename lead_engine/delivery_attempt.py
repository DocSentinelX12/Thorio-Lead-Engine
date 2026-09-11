from datetime import datetime, timezone
import hashlib
from typing import Any, Dict


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attempt_key(lead: Dict[str, Any], partner: str) -> str:
    """Build a stable, non-PII idempotency key for one lead/route/partner."""

    fingerprint = str(lead.get("fingerprint", "") or "").strip()
    identity = fingerprint or "|".join(
        str(lead.get(field, "") or "").strip().lower()
        for field in (
            "source_id",
            "company",
            "person",
            "contact_name",
            "business_need",
            "route",
        )
    )
    material = f"{identity}|{str(partner or '').strip().lower()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_delivery_attempt(
    lead: Dict[str, Any],
    partner: str,
) -> Dict[str, Any]:
    """Create an immutable delivery attempt descriptor with an idempotency key."""

    return {
        "attempt_key": _attempt_key(lead, partner),
        "source_id": lead.get("source_id", ""),
        "fingerprint": lead.get("fingerprint", ""),
        "company": lead.get("company", ""),
        "route": lead.get("route", ""),
        "partner": str(partner or "").strip(),
        "status": "pending",
        "attempted_at": _timestamp(),
    }


def complete_delivery_attempt(
    attempt: Dict[str, Any],
    success: bool,
    reason: str = "",
) -> Dict[str, Any]:
    """Complete an attempt without allowing a delivered result to be downgraded."""

    result = dict(attempt)
    current = str(result.get("status", "") or "").strip().lower()

    if current == "delivered":
        return result

    result["status"] = "delivered" if success else "failed"
    result["reason"] = str(reason or "").strip()
    result["completed_at"] = _timestamp()
    return result


def delivery_attempt_succeeded(attempt: Dict[str, Any]) -> bool:
    return str(attempt.get("status", "") or "").strip().lower() == "delivered"


def delivery_attempt_failed(attempt: Dict[str, Any]) -> bool:
    return str(attempt.get("status", "") or "").strip().lower() == "failed"
