from typing import Any, Dict, Iterable, List

from .partner_export import (
    PARTNER_ROUTES,
    build_partner_exports,
)


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
