import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .database import LeadDB
from .partner_export import (
    PARTNER_ROUTES,
    build_partner_exports,
)


def export_pending_leads(
    db: LeadDB,
    path: str,
) -> Dict[str, Any]:
    """
    Export the local pending queue to JSON.

    The local database remains authoritative.
    Exporting does not modify lead state.
    """

    destination = Path(path)

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = db.pending()

    leads = []

    for fingerprint, payload, attempts in rows:
        lead = json.loads(payload)

        lead["fingerprint"] = fingerprint
        lead["sync_attempts"] = attempts

        leads.append(lead)

    with destination.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            leads,
            handle,
            indent=2,
            ensure_ascii=False,
        )

    return {
        "path": str(destination),
        "count": len(leads),
    }


def export_partner_leads(
    leads: Iterable[Dict[str, Any]],
    partner: str,
) -> List[Dict[str, Any]]:
    """
    Return deliverable leads for one supported partner.
    """

    partner = str(partner or "").strip()

    if partner not in PARTNER_ROUTES:
        return []

    exports = build_partner_exports(leads)

    return exports[partner]


def export_all_partners(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Return deliverable leads grouped by partner.
    """

    return build_partner_exports(leads)
