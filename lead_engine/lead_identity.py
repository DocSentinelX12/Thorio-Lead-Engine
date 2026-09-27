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
        "identity_derivation": dict(derivation),
    }


def validate_materialized_opportunity_identity(payload: Dict[str, Any]) -> str:
    """Require and validate the complete canonical identity contract used by handoff."""
    if not isinstance(payload, dict):
        raise ValueError("Opportunity identity validation requires an object.")

    required_fields = ("opportunity_id", "fingerprint", "identity_version", "identity_derivation")
    missing = [field for field in required_fields if field not in payload or payload.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Canonical opportunity identity is incomplete; missing {', '.join(missing)}.")
    if normalize_identity_value(payload.get("identity_version")) != CANONICAL_IDENTITY_VERSION:
        raise ValueError("Unsupported canonical opportunity identity version.")
    derivation = payload.get("identity_derivation")
    if not isinstance(derivation, dict) or not derivation:
        raise ValueError("Canonical opportunity identity requires identity_derivation.")

    canonical = canonical_opportunity_identity(payload)
    if normalize_identity_value(payload.get("opportunity_id")) != canonical["opportunity_id"]:
        raise ValueError("opportunity_id does not match canonical opportunity identity.")
    if normalize_identity_value(payload.get("fingerprint")) != canonical["fingerprint"]:
        raise ValueError("fingerprint does not match canonical opportunity identity.")
    if derivation != canonical["identity_derivation"]:
        raise ValueError("identity_derivation does not match canonical opportunity identity.")
    validate_opportunity_identity(payload)
    return canonical["opportunity_id"]


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
        canonical_keys = (
            "source",
            "source_id",
            "url",
            "company",
            "person",
            "job_title",
            "signal_type",
            "discovered_at",
        )
        canonical_input = {}
        for key in canonical_keys:
            current_value = payload.get(key)
            if key == "url":
                current_value = payload.get("url") or payload.get("source_url")
            if key == "person":
                current_value = payload.get("person") or payload.get("contact_name")
            canonical_input[key] = (
                current_value
                if normalize_identity_value(current_value)
                else derivation.get(key)
            )

        expected_from_derivation = lead_identity({
            key: derivation.get(key)
            for key in canonical_keys
        })
        expected_from_payload = lead_identity(canonical_input)

        if expected_from_derivation != expected_from_payload:
            raise ValueError("canonical opportunity identity does not match current identity fields.")
        if fingerprint and expected_from_derivation != fingerprint:
            raise ValueError("fingerprint does not match canonical opportunity identity.")
        if opportunity_id and expected_from_derivation != opportunity_id:
            raise ValueError("opportunity_id does not match canonical opportunity identity.")
        return fingerprint or opportunity_id or expected_from_derivation

    if fingerprint:
        return fingerprint
    if opportunity_id:
        return opportunity_id

    return canonical_opportunity_identity(payload)["opportunity_id"]
