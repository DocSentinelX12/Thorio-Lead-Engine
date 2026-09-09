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
    Return a deterministic identity for one discovered opportunity.

    Identity is intentionally opportunity-level, not company-level.

    A company or person may generate many valid opportunities. When a
    source provides a stable source_id, the source event remains the
    primary identity, with URL and job title included when available so
    feeds that reuse a coarse source_id cannot collapse distinct roles.

    Without a source_id, normalized company + URL + job title + signal
    type define the opportunity. The signal text itself is deliberately
    excluded from the fallback identity so updated evidence for the same
    opportunity does not create a new record.
    """

    source = normalize_identity_value(
        lead.get("source")
    )

    source_id = normalize_identity_value(
        lead.get("source_id")
    )

    url = normalize_identity_value(
        lead.get("url") or lead.get("source_url")
    )

    job_title = normalize_identity_value(
        lead.get("job_title")
    )

    signal_type = normalize_identity_value(
        lead.get("signal_type")
    )

    if source and source_id:
        raw_identity = (
            f"source:{source}|"
            f"source_id:{source_id}|"
            f"url:{url}|"
            f"job_title:{job_title}"
        )
    else:
        company = normalize_identity_value(
            lead.get("company")
        )

        raw_identity = (
            f"company:{company}|"
            f"url:{url}|"
            f"job_title:{job_title}|"
            f"signal_type:{signal_type}"
        )

    return hashlib.sha256(
        raw_identity.encode("utf-8")
    ).hexdigest()


def add_lead_identity(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a copy of the lead with its deterministic opportunity identity attached.
    """

    result = dict(lead)

    result["lead_identity"] = lead_identity(
        result
    )

    return result
