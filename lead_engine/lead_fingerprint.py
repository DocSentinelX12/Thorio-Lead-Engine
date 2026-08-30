from __future__ import annotations

from typing import Any, Dict

from .lead_identity import lead_identity


def lead_fingerprint(lead: Dict[str, Any]) -> str:
    """Generate the canonical stable fingerprint for a lead."""
    return lead_identity(lead)


def same_lead(
    first: Dict[str, Any],
    second: Dict[str, Any],
) -> bool:
    """Return True when two records represent the same lead."""
    return lead_fingerprint(first) == lead_fingerprint(second)
