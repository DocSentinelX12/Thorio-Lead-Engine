from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


ASTRIVON_PARTNER = "Astrivon Labs"
ASTRIVON_ROUTE = "Astrivon Labs"
ASTRIVON_COMMISSION_RATE = Decimal("0.20")

ASTRIVON_SERVICE_SIGNALS = {
    "AI & Machine Learning Solutions": ("ai/ml", "machine learning", "ai developer", "ai engineer", "artificial intelligence"),
    "Computer Vision Applications": ("computer vision", "vision specialist", "vision developer", "vision engineer"),
    "Business Automation Systems": ("business workflow", "workflow automation", "crm automation", "sales automation", "automate business"),
    "End-to-End Product Development": ("mvp", "product development", "web/mobile app", "app build", "startup platform"),
    "Software Development at any stage, MVP to enterprise": ("dev agency", "tech partner", "full-stack software engineer", "software development", "scaling my web/mobile app"),
    "B2B Outreach & Lead Generation Infrastructure": ("b2b outreach", "b2b sales", "sales representative", "lead generation", "sales pipeline"),
}



def match_astrivon_services(text: str) -> tuple[str, ...]:
    lowered = str(text or "").lower()
    matched = []
    for service, signals in ASTRIVON_SERVICE_SIGNALS.items():
        if any(signal in lowered for signal in signals):
            matched.append(service)
    return tuple(matched)


class AstrivonReferralError(ValueError):
    """Raised when an Astrivon referral transition is invalid."""


@dataclass(frozen=True)
class AstrivonPaymentEvent:
    """One client payment actually received by Astrivon.

    Each event is independently attributable so recurring client revenue
    continues to generate a 20% referral commission without overwriting the
    original referral record.
    """

    event_id: str
    received_at: str
    revenue_amount: Decimal
    commission_rate: Decimal = ASTRIVON_COMMISSION_RATE

    @property
    def commission_amount(self) -> Decimal:
        return (self.revenue_amount * self.commission_rate).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class AstrivonReferral:
    fingerprint: str
    company: str
    contact_name: str = ""
    contact_email: str = ""
    current_need: str = ""
    verified_evidence: str = ""
    services: tuple[str, ...] = ()
    status: str = "qualified"
    human_approved: bool = False
    referral_id: str | None = None
    introduced_at: str | None = None
    partner_confirmed: bool = False
    payment_events: tuple[AstrivonPaymentEvent, ...] = ()

    @property
    def commission_rate(self) -> Decimal:
        return ASTRIVON_COMMISSION_RATE

    @property
    def revenue_received(self) -> Decimal:
        return sum((event.revenue_amount for event in self.payment_events), Decimal("0"))

    @property
    def commission_earned(self) -> Decimal:
        return sum((event.commission_amount for event in self.payment_events), Decimal("0"))

    def is_ready_for_introduction(self) -> bool:
        return bool(
            self.fingerprint.strip()
            and self.company.strip()
            and (self.contact_name.strip() or self.contact_email.strip())
            and self.current_need.strip()
            and self.verified_evidence.strip()
            and self.human_approved
            and self.status == "qualified"
        )

    def meeting_payload(self) -> dict[str, Any]:
        if not self.is_ready_for_introduction():
            raise AstrivonReferralError(
                "Astrivon meeting setup requires a human-approved qualified referral, "
                "verified need, verified evidence, and a named contact."
            )
        return {
            "partner": ASTRIVON_PARTNER,
            "route": ASTRIVON_ROUTE,
            "company": self.company.strip(),
            "contact_name": self.contact_name.strip(),
            "contact_email": self.contact_email.strip(),
            "current_need": self.current_need.strip(),
            "services": list(self.services),
            "evidence": self.verified_evidence.strip(),
            "execution_owner": "Astrivon Labs",
            "technical_discovery_owner": "Astrivon senior developers",
        }

    def mark_introduced(
        self,
        *,
        referral_id: str,
        introduced_at: str | None = None,
    ) -> "AstrivonReferral":
        referral_id = referral_id.strip()
        if not referral_id:
            raise AstrivonReferralError("Astrivon introduction requires a real referral ID.")
        if not self.is_ready_for_introduction():
            raise AstrivonReferralError(
                "Astrivon referral is not ready for introduction."
            )
        if self.referral_id:
            raise AstrivonReferralError("Astrivon referral has already been introduced.")
        timestamp = introduced_at.strip() if introduced_at else datetime.now(timezone.utc).isoformat()
        return AstrivonReferral(
            **{
                **self.__dict__,
                "status": "introduced",
                "referral_id": referral_id,
                "introduced_at": timestamp,
            }
        )

    def confirm_partner(self) -> "AstrivonReferral":
        if not self.referral_id:
            raise AstrivonReferralError(
                "Astrivon partner confirmation requires an introduced referral."
            )
        return AstrivonReferral(
            **{
                **self.__dict__,
                "status": "active",
                "partner_confirmed": True,
            }
        )

    def record_client_payment(
        self,
        *,
        event_id: str,
        revenue_amount: Any,
        received_at: str | None = None,
    ) -> "AstrivonReferral":
        if not self.referral_id or not self.partner_confirmed:
            raise AstrivonReferralError(
                "Astrivon client payment requires a confirmed introduced referral."
            )
        event_id = event_id.strip()
        if not event_id:
            raise AstrivonReferralError("Astrivon payment event requires an event ID.")
        if any(event.event_id == event_id for event in self.payment_events):
            raise AstrivonReferralError(
                f"Astrivon payment event already recorded: {event_id}"
            )
        try:
            amount = Decimal(str(revenue_amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise AstrivonReferralError("Astrivon revenue amount must be numeric.") from exc
        if amount <= 0:
            raise AstrivonReferralError("Astrivon revenue amount must be greater than zero.")
        timestamp = received_at.strip() if received_at else datetime.now(timezone.utc).isoformat()
        event = AstrivonPaymentEvent(
            event_id=event_id,
            received_at=timestamp,
            revenue_amount=amount,
        )
        return AstrivonReferral(
            **{
                **self.__dict__,
                "status": "active",
                "payment_events": (*self.payment_events, event),
            }
        )


def lead_to_astrivon_referral(lead: Mapping[str, Any]) -> AstrivonReferral:
    if not isinstance(lead, Mapping):
        raise AstrivonReferralError("Lead payload must be a mapping.")
    research = lead.get("route_research")
    route_item = {}
    if isinstance(research, Mapping):
        routes = research.get("routes")
        if isinstance(routes, Mapping) and isinstance(routes.get(ASTRIVON_ROUTE), Mapping):
            route_item = routes[ASTRIVON_ROUTE]
    services = lead.get("astrivon_services")
    if not isinstance(services, (list, tuple)):
        services = match_astrivon_services(" ".join((str(lead.get("signal") or ""), str(lead.get("evidence") or ""), str(lead.get("current_need") or ""), str(route_item.get("current_need") or ""), str(route_item.get("evidence") or ""))))
    return AstrivonReferral(
        fingerprint=str(lead.get("fingerprint") or "").strip(),
        company=str(lead.get("company") or "").strip(),
        contact_name=str(lead.get("contact_name") or lead.get("person") or "").strip(),
        contact_email=str(lead.get("contact_email") or "").strip(),
        current_need=str(
            lead.get("current_need")
            or lead.get("business_need")
            or route_item.get("current_need")
            or route_item.get("business_need")
            or ""
        ).strip(),
        verified_evidence=str(
            route_item.get("evidence")
            or route_item.get("business_need")
            or lead.get("evidence")
            or ""
        ).strip(),
        services=tuple(str(item).strip() for item in services if str(item).strip()),
        status=str(lead.get("astrivon_status") or "qualified").strip(),
        human_approved=lead.get("human_approved") is True,
        referral_id=str(lead.get("astrivon_referral_id") or "").strip() or None,
        introduced_at=str(lead.get("astrivon_introduced_at") or "").strip() or None,
        partner_confirmed=lead.get("astrivon_partner_confirmed") is True,
    )


def astrivon_referral_to_lead_fields(referral: AstrivonReferral) -> dict[str, Any]:
    return {
        "astrivon_status": referral.status,
        "astrivon_referral_id": referral.referral_id,
        "astrivon_introduced_at": referral.introduced_at,
        "astrivon_partner_confirmed": referral.partner_confirmed,
        "astrivon_commission_rate": float(referral.commission_rate),
        "astrivon_revenue_received": float(referral.revenue_received),
        "astrivon_commission_earned": float(referral.commission_earned),
        "astrivon_payment_event_ids": [event.event_id for event in referral.payment_events],
    }
