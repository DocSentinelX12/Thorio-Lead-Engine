from __future__ import annotations
import hashlib
import re
from typing import Any, Dict

def normalize_identity_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())

def lead_identity(lead: Dict[str, Any]) -> str:
    parts = (("source", lead.get("source")), ("source_id", lead.get("source_id")), ("url", lead.get("url") or lead.get("source_url")), ("company", lead.get("company")), ("person", lead.get("person") or lead.get("contact_name")), ("job_title", lead.get("job_title")), ("signal_type", lead.get("signal_type")), ("discovered_at", lead.get("discovered_at")))
    raw = "|".join(f"{key}:{normalize_identity_value(value)}" for key, value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def add_lead_identity(lead: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(lead)
    result["lead_identity"] = lead_identity(result)
    return result
