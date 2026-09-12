from __future__ import annotations

import pytest

from .shiftr_referral import ShiftrReferralError, lead_to_shiftr_referral
from .thorio_handoff import ThorioHandoffError, lead_to_thorio_job_draft


LEAD = {
    "fingerprint": "lead-1",
    "company": "Example Corp",
    "contact_name": "Hiring Lead",
    "contact_email": "hiring@example.com",
    "business_need": "AI engineering team for a production LLM integration",
    "role_title": "Senior AI Engineer",
    "location": "Remote, US",
    "employment_type": "full-time",
    "job_description": "Build and operate production AI systems.",
    "job_requirements": "Python, LLM APIs, cloud deployment",
    "compensation": "$160,000-$190,000",
}


def test_shiftr_requires_real_referral_fields_before_submission():
    referral = lead_to_shiftr_referral(
        LEAD,
        referrer_name="Thorio Lead Engine",
        referrer_email="referrer@example.com",
    )
    assert referral.is_ready_for_submission()
    payload = referral.submission_payload()
    assert payload["referred_company"] == "Example Corp"
    assert payload["project_needs"].startswith("AI engineering")


def test_shiftr_referral_cannot_claim_submission_without_real_confirmation():
    referral = lead_to_shiftr_referral(
        LEAD,
        referrer_name="Thorio Lead Engine",
        referrer_email="referrer@example.com",
    )
    with pytest.raises(ShiftrReferralError):
        referral.mark_submitted(
            referral_id="",
            submitted_at="2026-09-12T00:00:00Z",
            confirmation_source="",
        )


def test_thorio_job_draft_requires_employer_approval_before_handoff():
    draft = lead_to_thorio_job_draft(LEAD)
    assert draft.is_complete()
    with pytest.raises(ThorioHandoffError):
        draft.handoff(
            handoff_at="2026-09-12T00:00:00Z",
            handoff_reference="thorio-session-1",
        )
    approved = draft.approve()
    assert approved.approved is True
    handed_off = approved.handoff(
        handoff_at="2026-09-12T00:00:00Z",
        handoff_reference="thorio-session-1",
    )
    assert handed_off.handed_off is True
    assert handed_off.handoff_reference == "thorio-session-1"
