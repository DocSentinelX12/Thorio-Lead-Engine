from __future__ import annotations

from typing import Any, Dict, Iterable, List


def contact_email(lead: Dict[str, Any]) -> str:
    """Return a normalized contact email."""

    value = lead.get("contact_email", "")

    if value is None:
        return ""

    return str(value).strip().lower()


def has_contact_email(lead: Dict[str, Any]) -> bool:
    """Return True when a lead has a usable contact email."""

    email = contact_email(lead)

    return (
        bool(email)
        and "@" in email
        and "." in email.rsplit("@", 1)[-1]
    )


def filter_contactable_leads(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return copies of leads that have usable contact emails."""

    return [
        dict(lead)
        for lead in leads
        if has_contact_email(lead)
    ]
