from __future__ import annotations

import hashlib
import re
from typing import Any, Dict


def normalize_identity_value(value: Any) -> str:
    """
    Normalize a value for stable lead identity comparisons.
    """

    text = str(value or "").strip().lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text


def lead_identity(
    lead: Dict[str, Any],
) -> str:
    """
    Return a deterministic identity for a lead.

    Prefer source + source_id when available because those values
    identify the original discovered record.

    Fall back to normalized company + URL + signal when no source_id
    exists.
    """

    source = normalize_identity_value(
        lead.get("source")
    )

    source_id = normalize_identity_value(
        lead.get("source_id")
    )

    if source and source_id:
        raw_identity = (
            f"source:{source}|"
            f"source_id:{source_id}"
        )
    else:
        company = normalize_identity_value(
            lead.get("company")
        )

        url = normalize_identity_value(
            lead.get("url")
        )

        signal = normalize_identity_value(
            lead.get("signal")
        )

        raw_identity = (
            f"company:{company}|"
            f"url:{url}|"
            f"signal:{signal}"
        )

    return hashlib.sha256(
        raw_identity.encode("utf-8")
    ).hexdigest()


def add_lead_identity(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a copy of the lead with its deterministic identity attached.
    """

    result = dict(lead)

    result["lead_identity"] = lead_identity(
        result
    )

    return result
