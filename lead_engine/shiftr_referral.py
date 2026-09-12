from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


class ShiftrReferralError(ValueError):
    """Raised when a Shiftr referral cannot be safely prepared."""


@dataclass(frozen=True)
class ShiftrReferral:
    """Durable business payload for the real Shiftr referral form.

    This module owns validation and state mapping only. The actual external
    submission must use an explicitly configured, authenticated transport.
    No URL, selector, credential, or referral ID is invented here.
    """

    fingerprint: str
    referrer_name: str
    referrer_email: str
    company: str
    contact_name: str
    contact_email: str
    project_needs: str
    submitted: bool = False
    referral_id: str | None = None
    submitted_at: str | None = None
    confirmation_source: str | None = None

    def submission_payload(self) -> Dict[str, str]:
        if not self.is_ready_for_submission():
            raise ShiftrReferralError("Shiftr referral is missing required submission fields")
        return {
            "referrer_name": self.referrer_name,
            "referrer_email": self.referrer_email,
            "referred_name": self.contact_name,
            "referred_company": self.company,
            "referred_email": self.contact_email,
            "project_needs": self.project_needs,
        }

    def is_ready_for_submission(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.referrer_name,
                self.referrer_email,
                self.company,
                self.contact_name,
                self.contact_email,
                self.project_needs,
            )
        ) and not self.submitted

    def mark_submitted(
        self,
        *,
        referral_id: str,
        submitted_at: str,
        confirmation_source: str,
    ) -> "ShiftrReferral":
        referral_id = referral_id.strip()
        confirmation_source = confirmation_source.strip()
        if not referral_id or not confirmation_source:
            raise ShiftrReferralError("A real Shiftr referral ID and confirmation source are required")
        return ShiftrReferral(
            **{
                **self.__dict__,
                "submitted": True,
                "referral_id": referral_id,
                "submitted_at": submitted_at,
                "confirmation_source": confirmation_source,
            }
        )


def lead_to_shiftr_referral(
    lead: Mapping[str, Any],
    *,
    referrer_name: str,
    referrer_email: str,
) -> ShiftrReferral:
    """Build a Shiftr referral only from already-established lead evidence."""
    if not isinstance(lead, Mapping):
        raise ShiftrReferralError("Lead payload must be a mapping")
    contact = lead.get("contact_name") or lead.get("person")
    email = lead.get("contact_email")
    needs = lead.get("business_need") or lead.get("current_need") or lead.get("opportunity")
    return ShiftrReferral(
        fingerprint=str(lead.get("fingerprint") or "").strip(),
        referrer_name=str(referrer_name or "").strip(),
        referrer_email=str(referrer_email or "").strip(),
        company=str(lead.get("company") or "").strip(),
        contact_name=str(contact or "").strip(),
        contact_email=str(email or "").strip(),
        project_needs=str(needs or "").strip(),
        submitted=lead.get("shiftr_referral_submitted") is True,
        referral_id=str(lead.get("shiftr_referral_id") or "").strip() or None,
        submitted_at=str(lead.get("shiftr_referral_submitted_at") or "").strip() or None,
        confirmation_source=str(lead.get("shiftr_referral_confirmation_source") or "").strip() or None,
    )


def shiftr_referral_to_lead_fields(referral: ShiftrReferral) -> Dict[str, Any]:
    return {
        "shiftr_referral_submitted": referral.submitted,
        "shiftr_referral_id": referral.referral_id,
        "shiftr_referral_submitted_at": referral.submitted_at,
        "shiftr_referral_confirmation_source": referral.confirmation_source,
    }
