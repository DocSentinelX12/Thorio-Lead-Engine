from __future__ import annotations

from typing import Any, Dict, Iterable, List


def summarize_lead(lead: Dict[str, Any]) -> str:
    """Create a concise human-readable lead summary."""

    company = str(lead.get("company", "") or "").strip()
    route = str(lead.get("route", "") or "").strip()
    signal = str(lead.get("signal", "") or "").strip()
    contact = str(
        lead.get("contact_name", "")
        or lead.get("person", "")
        or ""
    ).strip()

    parts: List[str] = []

    if company:
        parts.append(company)

    if contact:
        parts.append(f"contact: {contact}")

    if route:
        parts.append(f"route: {route}")

    if signal:
        parts.append(f"signal: {signal}")

    return " | ".join(parts)


def summarize_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[str]:
    """Create summaries for multiple leads."""

    return [
        summarize_lead(lead)
        for lead in leads
    ]
