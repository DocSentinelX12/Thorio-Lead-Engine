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


def test_astrivon_meeting_setup_does_not_require_human_approval():
    referral = _referral(human_approved=False)
    payload = referral.meeting_payload()
    assert payload["partner"] == "Astrivon Labs"
    assert payload["execution_owner"] == "Astrivon Labs"


def test_astrivon_introduction_does_not_require_partner_referral_id():
    introduced = _referral(human_approved=False).mark_introduced()
    assert introduced.status == "introduced"
    assert introduced.referral_id is None
    assert introduced.introduced_at


def test_astrivon_payment_is_20_percent_of_received_revenue():
    referral = _referral().mark_introduced().confirm_partner(referral_id="astr-001")
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
    assert "End-to-End Product Development" in referral.services
    assert referral.verified_evidence.startswith("Acme needs")


def test_astrivon_lifecycle_supports_referred_introduced_active_closed_and_ended():
    from lead_engine.astrivon_referral import AstrivonReferral
    referral = AstrivonReferral(
        fingerprint="fp",
        company="Acme",
        contact_name="Jane Doe",
        current_need="Build an MVP",
        verified_evidence="https://example.com/need",
        human_approved=True,
    )
    referred = referral.mark_referred()
    introduced = referred.mark_introduced(introduced_at="2026-09-26T00:00:00+00:00")
    active = introduced.confirm_partner(referral_id="astr-1")
    closed = active.mark_closed()
    ended = closed.mark_ended()
    assert referred.status == "referred"
    assert introduced.status == "introduced"
    assert active.status == "active"
    assert closed.status == "closed"
    assert ended.status == "ended"
