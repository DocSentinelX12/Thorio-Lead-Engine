from __future__ import annotations

from typing import Any, Dict

from .paxus_referral import PaxusReferral


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _bool(value: Any) -> bool:
    return value is True


def lead_to_paxus_referral(
    lead: Dict[str, Any],
) -> PaxusReferral:
    """
    Convert an existing Thorio lead payload into the Paxus
    referral state model.

    This function does not qualify the lead, route the lead,
    deduplicate the lead, send outreach, or submit a referral.

    It only maps already stored lead data into the Paxus model.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    return PaxusReferral(
        fingerprint=_text(
            lead.get("fingerprint")
        ),
        company=_text(
            lead.get("company")
        ),
        contact_name=_text(
            lead.get("contact_name")
            or lead.get("person")
        ) or None,
        contact_email=_text(
            lead.get("contact_email")
        ) or None,
        contact_communicated=_bool(
            lead.get("contact_communicated")
        ),
        contact_consent=_bool(
            lead.get("contact_consent")
        ),
        warm_referral_ready=_bool(
            lead.get("warm_referral_ready")
        ),
        referral_submitted=_bool(
            lead.get("referral_submitted")
        ),
        paxus_accepted=_bool(
            lead.get("paxus_accepted")
        ),
        referral_id=_text(
            lead.get("referral_id")
        ) or None,
        introduction_made=_bool(
            lead.get("introduction_made")
        ),
        recruiting_status=(
            _text(
                lead.get("recruiting_status")
            )
            or "not_started"
        ),
        placement_count=int(
            lead.get(
                "placement_count",
                0,
            ) or 0
        ),
        client_payment_received=_bool(
            lead.get("client_payment_received")
        ),
        commission_due=_bool(
            lead.get("commission_due")
        ),
        submitted_at=_text(
            lead.get("submitted_at")
        ) or None,
        accepted_at=_text(
            lead.get("accepted_at")
        ) or None,
        introduction_deadline=_text(
            lead.get("introduction_deadline")
        ) or None,
        introduced_at=_text(
            lead.get("introduced_at")
        ) or None,
    )


def paxus_referral_to_lead_fields(
    referral: PaxusReferral,
) -> Dict[str, Any]:
    """
    Convert Paxus referral state into fields that can be
    persisted alongside the existing Thorio lead.

    This function never removes or replaces unrelated lead fields.
    """

    return {
        "contact_communicated": referral.contact_communicated,
        "contact_consent": referral.contact_consent,
        "warm_referral_ready": referral.warm_referral_ready,
        "referral_submitted": referral.referral_submitted,
        "paxus_accepted": referral.paxus_accepted,
        "referral_id": referral.referral_id,
        "introduction_made": referral.introduction_made,
        "recruiting_status": referral.recruiting_status,
        "placement_count": referral.placement_count,
        "client_payment_received": referral.client_payment_received,
        "commission_due": referral.commission_due,
        "submitted_at": referral.submitted_at,
        "accepted_at": referral.accepted_at,
        "introduction_deadline": referral.introduction_deadline,
        "introduced_at": referral.introduced_at,
    }


def merge_paxus_referral_into_lead(
    lead: Dict[str, Any],
    referral: PaxusReferral,
) -> Dict[str, Any]:
    """
    Return a copy of the existing lead with Paxus referral
    state merged into it.

    Existing lead fields are preserved unless they are fields
    owned by the Paxus referral state.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    updated = dict(lead)

    updated.update(
        paxus_referral_to_lead_fields(
            referral
        )
    )

    return updated


def paxus_referral_is_applicable(
    lead: Dict[str, Any],
) -> bool:
    """
    Determine whether Paxus referral handling is applicable
    to an already qualified lead.

    Routing remains owned by the existing three-route system.
    """

    if not isinstance(lead, dict):
        return False

    if lead.get("qualified") is not True:
        return False

    routes = lead.get("potential_routes", [])

    if isinstance(routes, str):
        routes = [routes]

    if not isinstance(routes, list):
        return False

    normalized_routes = {
        _text(route).lower()
        for route in routes
    }

    return "paxus" in normalized_routes


def paxus_referral_ready_for_outreach(
    lead: Dict[str, Any],
) -> bool:
    """
    Outreach readiness requires a qualified Paxus lead and
    a real decision-maker contact.

    Consent is intentionally not inferred here.
    """

    if not paxus_referral_is_applicable(lead):
        return False

    contact_name = _text(
        lead.get("contact_name")
        or lead.get("person")
    )

    contact_email = _text(
        lead.get("contact_email")
    )

    return bool(
        contact_name
        and (
            contact_email
            or _text(
                lead.get("linkedin_url")
            )
        )
    )


def paxus_referral_ready_for_submission(
    lead: Dict[str, Any],
) -> bool:
    """
    Submission readiness requires an actual warm referral.

    A discovered company, job posting, contact record, or
    cold outreach attempt is not enough.
    """

    if not paxus_referral_is_applicable(lead):
        return False

    return (
        lead.get("contact_communicated") is True
        and lead.get("contact_consent") is True
        and lead.get("warm_referral_ready") is True
        and lead.get("referral_submitted") is False
    )


def paxus_referral_ready_for_introduction(
    lead: Dict[str, Any],
) -> bool:
    """
    Direct introduction is allowed only after Paxus acceptance
    and a Referral ID have been recorded.
    """

    if not paxus_referral_is_applicable(lead):
        return False

    return (
        lead.get("referral_submitted") is True
        and lead.get("paxus_accepted") is True
        and bool(
            _text(
                lead.get("referral_id")
            )
        )
        and lead.get("introduction_made") is False
    )


def paxus_commission_tracking_enabled(
    lead: Dict[str, Any],
) -> bool:
    """
    Commission tracking becomes active after a qualifying
    placement and confirmed client payment.

    The existing Paxus referral state remains authoritative.
    """

    if not paxus_referral_is_applicable(lead):
        return False

    try:
        placement_count = int(
            lead.get(
                "placement_count",
                0,
            ) or 0
        )
    except (TypeError, ValueError):
        return False

    return (
        placement_count > 0
        and lead.get("client_payment_received") is True
    )
