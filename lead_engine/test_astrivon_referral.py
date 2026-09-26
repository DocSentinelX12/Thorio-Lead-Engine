from decimal import Decimal

import pytest

from .astrivon_referral import (
    ASTRIVON_COMMISSION_RATE,
    AstrivonReferral,
    AstrivonReferralError,
    lead_to_astrivon_referral,
)


def _referral(**overrides):
    values = {
        "fingerprint": "fp-astrivon-001",
        "company": "Acme",
        "contact_name": "Jane Doe",
        "contact_email": "jane@example.com",
        "current_need": "Need an MVP built for the startup",
        "verified_evidence": "Acme publicly stated that it needs an MVP built.",
        "services": ("End-to-End Product Development",),
        "human_approved": True,
    }
    values.update(overrides)
    return AstrivonReferral(**values)


def test_astrivon_requires_human_approval_before_meeting_setup():
    referral = _referral(human_approved=False)
    with pytest.raises(AstrivonReferralError, match="human-approved"):
        referral.meeting_payload()


def test_astrivon_introduction_requires_real_referral_id():
    with pytest.raises(AstrivonReferralError, match="real referral ID"):
        _referral().mark_introduced(referral_id="")


def test_astrivon_payment_is_20_percent_of_received_revenue():
    referral = _referral().mark_introduced(referral_id="astr-001").confirm_partner()
    referral = referral.record_client_payment(
        event_id="payment-001",
        revenue_amount="1250.00",
    )
    assert referral.commission_rate == ASTRIVON_COMMISSION_RATE
    assert referral.revenue_received == Decimal("1250.00")
    assert referral.commission_earned == Decimal("250.00")


def test_astrivon_recurring_payments_accumulate_independently():
    referral = _referral().mark_introduced(referral_id="astr-001").confirm_partner()
    referral = referral.record_client_payment(
        event_id="payment-001",
        revenue_amount="1000.00",
    )
    referral = referral.record_client_payment(
        event_id="payment-002",
        revenue_amount="600.00",
    )
    assert len(referral.payment_events) == 2
    assert referral.revenue_received == Decimal("1600.00")
    assert referral.commission_earned == Decimal("320.00")


def test_astrivon_duplicate_payment_event_is_rejected():
    referral = _referral().mark_introduced(referral_id="astr-001").confirm_partner()
    referral = referral.record_client_payment(
        event_id="payment-001",
        revenue_amount="100.00",
    )
    with pytest.raises(AstrivonReferralError, match="already recorded"):
        referral.record_client_payment(
            event_id="payment-001",
            revenue_amount="100.00",
        )


def test_lead_conversion_uses_verified_route_research():
    lead = {
        "fingerprint": "fp-astrivon-001",
        "company": "Acme",
        "person": "Jane Doe",
        "contact_email": "jane@example.com",
        "business_need": "Build an MVP",
        "route_research": {
            "verified": True,
            "routes": {
                "Astrivon Labs": {
                    "verified": True,
                    "evidence": "Acme needs an MVP built for its startup.",
                    "current_need": "Build an MVP",
                }
            },
        },
        "astrivon_services": ["End-to-End Product Development"],
        "human_approved": True,
    }
    referral = lead_to_astrivon_referral(lead)
    assert referral.company == "Acme"
    assert referral.current_need == "Build an MVP"
    assert referral.verified_evidence.startswith("Acme needs")
