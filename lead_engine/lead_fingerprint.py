from __future__ import annotations

import hashlib
import re
from typing import Any, Dict


def _normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def lead_fingerprint(
    lead: Dict[str, Any],
) -> str:
    """
    Generate a stable fingerprint for a lead.

    Prefer source identity when available. Otherwise use
    the core identifying lead fields.
    """

    source = _normalize(lead.get("source"))
    source_id = _normalize(lead.get("source_id"))

    if source and source_id:
        identity = f"{source}|{source_id}"
    else:
        identity = "|".join(
            (
                _normalize(lead.get("company")),
                _normalize(lead.get("person")),
                _normalize(lead.get("url")),
                _normalize(lead.get("signal")),
            )
        )

    return hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()


def same_lead(
    first: Dict[str, Any],
    second: Dict[str, Any],
) -> bool:
    """Return True when two records represent the same lead."""

    return lead_fingerprint(first) == lead_fingerprint(second)
