from __future__ import annotations

import hashlib
import re
from typing import Any, Dict


def normalize_identity_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def lead_identity(lead: Dict[str, Any]) -> str:
    parts = (
        ("source", lead.get("source")),
        ("source_id", lead.get("source_id")),
        ("url", lead.get("url") or lead.get("source_url")),
        ("company", lead.get("company")),
        ("person", lead.get("person") or lead.get("contact_name")),
        ("job_title", lead.get("job_title")),
        ("signal_type", lead.get("signal_type")),
        ("discovered_at", lead.get("discovered_at")),
    )
    raw = "|".join(f"{key}:{normalize_identity_value(value)}" for key, value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def add_lead_identity(lead: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(lead)
    result["lead_identity"] = lead_identity(result)
    return result


CANONICAL_IDENTITY_VERSION = "1"


def canonical_opportunity_identity(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Return the immutable identity contract for one opportunity."""
    if not isinstance(lead, dict):
        raise ValueError("Opportunity identity requires an object.")

    fingerprint = lead_identity(lead)
    derivation = {
        "source": normalize_identity_value(lead.get("source")),
        "source_id": normalize_identity_value(lead.get("source_id")),
        "url": normalize_identity_value(lead.get("url") or lead.get("source_url")),
        "company": normalize_identity_value(lead.get("company")),
        "company_website": normalize_identity_value(lead.get("company_website") or lead.get("website") or lead.get("domain")),
        "person": normalize_identity_value(lead.get("person") or lead.get("contact_name")),
        "contact_name": normalize_identity_value(lead.get("contact_name") or lead.get("person")),
        "contact_title": normalize_identity_value(lead.get("contact_title")),
        "contact_email": normalize_identity_value(lead.get("contact_email")),
        "linkedin_url": normalize_identity_value(lead.get("linkedin_url")),
        "job_title": normalize_identity_value(lead.get("job_title")),
        "signal_type": normalize_identity_value(lead.get("signal_type")),
        "discovered_at": normalize_identity_value(lead.get("discovered_at")),
    }
    return {
        "opportunity_id": fingerprint,
        "fingerprint": fingerprint,
        "identity_version": CANONICAL_IDENTITY_VERSION,
        "derivation": derivation,
    }


def validate_opportunity_identity(payload: Dict[str, Any]) -> str:
    """Validate that stored identity fields are internally consistent."""
    if not isinstance(payload, dict):
        raise ValueError("Opportunity identity validation requires an object.")

    fingerprint = normalize_identity_value(payload.get("fingerprint"))
    opportunity_id = normalize_identity_value(payload.get("opportunity_id"))

    if fingerprint and opportunity_id and fingerprint != opportunity_id:
        raise ValueError("opportunity_id must match fingerprint.")

    derivation = payload.get("identity_derivation")
    has_canonical_derivation = (
        normalize_identity_value(payload.get("identity_version")) == CANONICAL_IDENTITY_VERSION
        and isinstance(derivation, dict)
        and bool(derivation)
    )

    if has_canonical_derivation:
        canonical_input = {
            "source": derivation.get("source"),
            "source_id": derivation.get("source_id"),
            "url": derivation.get("url"),
            "company": derivation.get("company"),
            "person": derivation.get("person"),
            "job_title": derivation.get("job_title"),
            "signal_type": derivation.get("signal_type"),
            "discovered_at": derivation.get("discovered_at"),
        }
        expected = lead_identity(canonical_input)
        if fingerprint and expected != fingerprint:
            raise ValueError("fingerprint does not match canonical opportunity identity.")
        if opportunity_id and expected != opportunity_id:
            raise ValueError("opportunity_id does not match canonical opportunity identity.")
        return fingerprint or opportunity_id or expected

    if fingerprint:
        return fingerprint
    if opportunity_id:
        return opportunity_id

    return canonical_opportunity_identity(payload)["opportunity_id"]
