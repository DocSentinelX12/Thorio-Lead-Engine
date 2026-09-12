from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


class ThorioHandoffError(ValueError):
    """Raised when a Thorio sales handoff is not ready."""


@dataclass(frozen=True)
class ThorioJobDraft:
    """Employer-approved job-post data prepared by the Lead Engine.

    Thorio remains a completely separate business and system. This object is
    only the Lead Engine's side of the handoff. It does not implement Stripe,
    job publishing, or Thorio's internal APIs.
    """

    fingerprint: str
    company: str
    title: str
    location: str
    employment_type: str
    description: str
    requirements: str
    compensation: str
    contact_name: str
    contact_email: str
    approved: bool = False
    handed_off: bool = False
    handoff_at: str | None = None
    handoff_reference: str | None = None

    def is_complete(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.fingerprint,
                self.company,
                self.title,
                self.location,
                self.employment_type,
                self.description,
                self.requirements,
                self.contact_name,
                self.contact_email,
            )
        )

    def approve(self) -> "ThorioJobDraft":
        if not self.is_complete():
            raise ThorioHandoffError("Thorio job draft is incomplete")
        return ThorioJobDraft(**{**self.__dict__, "approved": True})

    def handoff(self, *, handoff_at: str, handoff_reference: str) -> "ThorioJobDraft":
        if not self.approved:
            raise ThorioHandoffError("Thorio job draft must be employer-approved before handoff")
        reference = handoff_reference.strip()
        if not reference:
            raise ThorioHandoffError("A real Thorio handoff reference is required")
        return ThorioJobDraft(
            **{
                **self.__dict__,
                "handed_off": True,
                "handoff_at": handoff_at,
                "handoff_reference": reference,
            }
        )


def lead_to_thorio_job_draft(lead: Mapping[str, Any]) -> ThorioJobDraft:
    """Create the Lead Engine's job-post draft from established opportunity data."""
    if not isinstance(lead, Mapping):
        raise ThorioHandoffError("Lead payload must be a mapping")
    job = lead.get("job_post_draft")
    if not isinstance(job, Mapping):
        job = {}
    return ThorioJobDraft(
        fingerprint=str(lead.get("fingerprint") or "").strip(),
        company=str(lead.get("company") or "").strip(),
        title=str(job.get("title") or lead.get("role_title") or lead.get("job_title") or "").strip(),
        location=str(job.get("location") or lead.get("location") or "").strip(),
        employment_type=str(job.get("employment_type") or lead.get("employment_type") or "").strip(),
        description=str(job.get("description") or lead.get("job_description") or "").strip(),
        requirements=str(job.get("requirements") or lead.get("job_requirements") or "").strip(),
        compensation=str(job.get("compensation") or lead.get("compensation") or "").strip(),
        contact_name=str(lead.get("contact_name") or lead.get("person") or "").strip(),
        contact_email=str(lead.get("contact_email") or "").strip(),
        approved=lead.get("thorio_job_draft_approved") is True,
        handed_off=lead.get("thorio_handoff_complete") is True,
        handoff_at=str(lead.get("thorio_handoff_at") or "").strip() or None,
        handoff_reference=str(lead.get("thorio_handoff_reference") or "").strip() or None,
    )


def thorio_job_draft_to_lead_fields(draft: ThorioJobDraft) -> Dict[str, Any]:
    return {
        "job_post_draft": {
            "title": draft.title,
            "location": draft.location,
            "employment_type": draft.employment_type,
            "description": draft.description,
            "requirements": draft.requirements,
            "compensation": draft.compensation,
        },
        "thorio_job_draft_approved": draft.approved,
        "thorio_handoff_complete": draft.handed_off,
        "thorio_handoff_at": draft.handoff_at,
        "thorio_handoff_reference": draft.handoff_reference,
    }
