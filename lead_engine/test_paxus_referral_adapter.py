from .paxus_referral import PaxusReferral
from .paxus_referral_adapter import (
    lead_to_paxus_referral,
    merge_paxus_referral_into_lead,
    paxus_commission_tracking_enabled,
    paxus_referral_is_applicable,
    paxus_referral_ready_for_introduction,
    paxus_referral_ready_for_outreach,
    paxus_referral_ready_for_submission,
)


def qualified_paxus_lead():
    return {
        "fingerprint": "paxus-adapter-001",
        "company": "Acme Corp",
        "person": "Jane Smith",
        "contact_name": "Jane Smith",
        "contact_email": "jane@example.com",
        "linkedin_url": "",
        "qualified": True,
        "potential_routes": ["Paxus"],
        "contact_communicated": False,
        "contact_consent": False,
        "warm_referral_ready": False,
        "referral_submitted": False,
        "paxus_accepted": False,
        "referral_id": None,
        "introduction_made": False,
        "placement_count": 0,
        "client_payment_received": False,
    }


def test_unqualified_lead_is_not_paxus_applicable():
    lead = qualified_paxus_lead()
    lead["qualified"] = False

    assert paxus_referral_is_applicable(lead) is False


def test_qualified_paxus_lead_is_applicable():
    lead = qualified_paxus_lead()

    assert paxus_referral_is_applicable(lead) is True


def test_outreach_requires_contact():
    lead = qualified_paxus_lead()
    lead["contact_name"] = ""
    lead["contact_email"] = ""

    assert paxus_referral_ready_for_outreach(lead) is False


def test_qualified_paxus_lead_can_be_prepared_for_outreach():
    lead = qualified_paxus_lead()

    assert paxus_referral_ready_for_outreach(lead) is True


def test_cold_lead_cannot_be_submitted():
    lead = qualified_paxus_lead()

    assert paxus_referral_ready_for_submission(lead) is False


def test_consent_and_communication_enable_submission():
    lead = qualified_paxus_lead()

    lead["contact_communicated"] = True
    lead["contact_consent"] = True
    lead["warm_referral_ready"] = True

    assert paxus_referral_ready_for_submission(lead) is True


def test_submission_does_not_mean_acceptance():
    lead = qualified_paxus_lead()

    lead["contact_communicated"] = True
    lead["contact_consent"] = True
    lead["warm_referral_ready"] = True
    lead["referral_submitted"] = True

    assert (
        paxus_referral_ready_for_introduction(lead)
        is False
    )


def test_acceptance_and_referral_id_enable_introduction():
    lead = qualified_paxus_lead()

    lead["contact_communicated"] = True
    lead["contact_consent"] = True
    lead["warm_referral_ready"] = True
    lead["referral_submitted"] = True
    lead["paxus_accepted"] = True
    lead["referral_id"] = "REF-001"

    assert (
        paxus_referral_ready_for_introduction(lead)
        is True
    )


def test_payment_without_placement_does_not_enable_commission():
    lead = qualified_paxus_lead()

    lead["client_payment_received"] = True

    assert (
        paxus_commission_tracking_enabled(lead)
        is False
    )


def test_paid_placement_enables_commission_tracking():
    lead = qualified_paxus_lead()

    lead["placement_count"] = 1
    lead["client_payment_received"] = True

    assert (
        paxus_commission_tracking_enabled(lead)
        is True
    )


def test_lead_to_paxus_referral_preserves_state():
    lead = qualified_paxus_lead()

    lead["contact_communicated"] = True
    lead["contact_consent"] = True
    lead["warm_referral_ready"] = True
    lead["referral_submitted"] = True
    lead["paxus_accepted"] = True
    lead["referral_id"] = "REF-001"
    lead["introduction_made"] = True
    lead["placement_count"] = 1
    lead["client_payment_received"] = True

    referral = lead_to_paxus_referral(lead)

    assert isinstance(referral, PaxusReferral)
    assert referral.fingerprint == lead["fingerprint"]
    assert referral.company == lead["company"]
    assert referral.contact_name == lead["contact_name"]
    assert referral.contact_email == lead["contact_email"]
    assert referral.contact_communicated is True
    assert referral.contact_consent is True
    assert referral.warm_referral_ready is True
    assert referral.referral_submitted is True
    assert referral.paxus_accepted is True
    assert referral.referral_id == "REF-001"
    assert referral.introduction_made is True
    assert referral.placement_count == 1
    assert referral.client_payment_received is True


def test_merge_preserves_unrelated_lead_fields():
    lead = qualified_paxus_lead()
    lead["lead_score"] = 91
    lead["priority"] = "Hot"
    lead["signal"] = "remote engineering hiring"

    referral = PaxusReferral(
        fingerprint="paxus-adapter-001",
        company="Acme Corp",
        contact_name="Jane Smith",
        contact_email="jane@example.com",
        contact_communicated=True,
        contact_consent=True,
        warm_referral_ready=True,
    )

    merged = merge_paxus_referral_into_lead(
        lead,
        referral,
    )

    assert merged["lead_score"] == 91
    assert merged["priority"] == "Hot"
    assert merged["signal"] == "remote engineering hiring"

    assert merged["contact_communicated"] is True
    assert merged["contact_consent"] is True
    assert merged["warm_referral_ready"] is True
