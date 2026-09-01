from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


PAXUS_ROUTE = "paxus"
INTRODUCTION_DEADLINE_BUSINESS_DAYS = 10
COMMISSION_PERIOD_MONTHS = 12


class PaxusReferralError(ValueError):
    """Raised when a Paxus referral transition is invalid."""


@dataclass(frozen=True)
class PaxusReferral:
    fingerprint: str
    company: str
    contact_name: str | None = None
    contact_email: str | None = None

    contact_communicated: bool = False
    contact_consent: bool = False
    warm_referral_ready: bool = False

    referral_submitted: bool = False
    paxus_accepted: bool = False
    referral_id: str | None = None

    introduction_made: bool = False
    recruiting_status: str = "not_started"

    placement_count: int = 0
    client_payment_received: bool = False
    commission_due: bool = False

    submitted_at: str | None = None
    accepted_at: str | None = None
    introduction_deadline: str | None = None
    introduced_at: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _add_business_days(start: datetime, days: int) -> datetime:
    current = start
    remaining = days

    while remaining:
        current += timedelta(days=1)

        if current.weekday() < 5:
            remaining -= 1

    return current


def _require_company(referral: PaxusReferral) -> None:
    if not referral.company.strip():
        raise PaxusReferralError("Paxus referral requires a company")


def _require_contact(referral: PaxusReferral) -> None:
    if not referral.contact_name and not referral.contact_email:
        raise PaxusReferralError(
            "Paxus referral requires a named hiring contact"
        )


def qualify_for_paxus(
    referral: PaxusReferral,
) -> bool:
    """
    A lead can enter the Paxus referral workflow only after
    qualification and a real hiring-contact interaction.
    """
    _require_company(referral)
    _require_contact(referral)

    return (
        referral.contact_communicated
        and referral.contact_consent
    )


def mark_warm_referral_ready(
    referral: PaxusReferral,
) -> PaxusReferral:
    if not qualify_for_paxus(referral):
        raise PaxusReferralError(
            "Contact communication and consent are required "
            "before a Paxus warm referral can be created"
        )

    return PaxusReferral(
        **{
            **referral.__dict__,
            "warm_referral_ready": True,
        }
    )


def submit_referral(
    referral: PaxusReferral,
) -> PaxusReferral:
    if not referral.warm_referral_ready:
        raise PaxusReferralError(
            "Paxus referral must be warm-referral-ready before submission"
        )

    if referral.referral_submitted:
        raise PaxusReferralError(
            "Paxus referral has already been submitted"
        )

    submitted_at = _utc_now()

    return PaxusReferral(
        **{
            **referral.__dict__,
            "referral_submitted": True,
            "submitted_at": _iso(submitted_at),
        }
    )


def accept_referral(
    referral: PaxusReferral,
    referral_id: str,
) -> PaxusReferral:
    if not referral.referral_submitted:
        raise PaxusReferralError(
            "Paxus cannot accept a referral before submission"
        )

    if referral.paxus_accepted:
        raise PaxusReferralError(
            "Paxus referral has already been accepted"
        )

    if not referral_id.strip():
        raise PaxusReferralError(
            "Accepted Paxus referral requires a Referral ID"
        )

    accepted_at = _utc_now()
    deadline = _add_business_days(
        accepted_at,
        INTRODUCTION_DEADLINE_BUSINESS_DAYS,
    )

    return PaxusReferral(
        **{
            **referral.__dict__,
            "paxus_accepted": True,
            "referral_id": referral_id.strip(),
            "accepted_at": _iso(accepted_at),
            "introduction_deadline": _iso(deadline),
        }
    )


def mark_introduction_made(
    referral: PaxusReferral,
) -> PaxusReferral:
    if not referral.paxus_accepted:
        raise PaxusReferralError(
            "Paxus referral must be accepted before introduction"
        )

    if not referral.referral_id:
        raise PaxusReferralError(
            "Paxus introduction requires a Referral ID"
        )

    if referral.introduction_deadline:
        deadline = _parse_datetime(referral.introduction_deadline)

        if _utc_now() > deadline:
            raise PaxusReferralError(
                "Paxus introduction deadline has passed"
            )

    return PaxusReferral(
        **{
            **referral.__dict__,
            "introduction_made": True,
            "introduced_at": _iso(_utc_now()),
        }
    )


def record_placement(
    referral: PaxusReferral,
) -> PaxusReferral:
    if not referral.introduction_made:
        raise PaxusReferralError(
            "Placement cannot be recorded before introduction"
        )

    return PaxusReferral(
        **{
            **referral.__dict__,
            "placement_count": referral.placement_count + 1,
            "recruiting_status": "placed",
        }
    )


def record_client_payment(
    referral: PaxusReferral,
) -> PaxusReferral:
    if referral.placement_count <= 0:
        raise PaxusReferralError(
            "Client payment cannot be recorded before placement"
        )

    return PaxusReferral(
        **{
            **referral.__dict__,
            "client_payment_received": True,
            "commission_due": True,
        }
    )


def can_deliver_to_paxus(
    referral: PaxusReferral,
) -> bool:
    """
    Final partner-delivery gate.

    A Paxus referral is deliverable only after:
    qualification
    -> contact communication
    -> contact consent
    -> warm referral
    -> submission
    -> Paxus acceptance
    -> Referral ID
    -> direct introduction
    """
    return (
        referral.warm_referral_ready
        and referral.referral_submitted
        and referral.paxus_accepted
        and bool(referral.referral_id)
        and referral.introduction_made
    )


def commission_status(
    referral: PaxusReferral,
) -> dict[str, Any]:
    return {
        "placement_count": referral.placement_count,
        "client_payment_received": referral.client_payment_received,
        "commission_due": referral.commission_due,
        "commission_rate_percent": 25,
        "commission_period_months": COMMISSION_PERIOD_MONTHS,
    }
