from typing import Any, Dict, Iterable, List


PARTNER_ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


def build_partner_exports(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build partner-specific exports from leads that already have
    an assigned supported partner route.

    This function is an export/grouping utility. It does not perform
    final delivery authorization, delivery-quality validation, or
    human approval checks.

    Final delivery eligibility is enforced by the delivery boundary.
    """

    exports = {
        route: []
        for route in PARTNER_ROUTES
    }

    for lead in leads:
        route = str(
            lead.get("route", "")
            or ""
        ).strip()

        if route not in PARTNER_ROUTES:
            continue

        exports[route].append(
            prepare_partner_lead(lead)
        )

    return exports


def prepare_partner_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize a lead into the stable partner export shape.
    """

    return {
        "source": lead.get("source", ""),
        "source_id": lead.get("source_id", ""),
        "url": lead.get("url", ""),
        "company": lead.get("company", ""),
        "person": lead.get("person", ""),
        "contact_name": lead.get(
            "contact_name",
            "",
        ),
        "contact_title": lead.get(
            "contact_title",
            "",
        ),
        "contact_email": lead.get(
            "contact_email",
            "",
        ),
        "signal": lead.get("signal", ""),
        "evidence": lead.get("evidence", ""),
        "route": lead.get("route", ""),
        "potential_routes": lead.get(
            "potential_routes",
            [],
        ),
        "lead_score": lead.get(
            "lead_score",
            0,
        ),
        "priority": lead.get(
            "priority",
            "",
        ),
        "status": lead.get(
            "status",
            "",
        ),
    }


def partner_export_summary(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Return the number of exported leads for each supported partner route.
    """

    exports = build_partner_exports(leads)

    return {
        partner: len(exports[partner])
        for partner in PARTNER_ROUTES
    }
