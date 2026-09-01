import pytest

from .paxus_referral import (
    PaxusReferral,
    PaxusReferralError,
    accept_referral,
    can_deliver_to_paxus,
    mark_introduction_made,
    mark_warm_referral_ready,
    record_client_payment,
    record_placement,
    submit_referral,
)


def base_referral(**overrides):
    values = {
        "fingerprint": "paxus-test-001",
        "company": "Acme Corp",
        "contact_name": "Jane Smith",
        "contact_email": "jane@example.com",
        "contact_communicated": True,
        "contact_consent": True,
    }

    values.update(overrides)

    return PaxusReferral(**values)


def test_contact_consent_is_required():
    referral = base_referral(contact_consent=False)

    with pytest.raises(PaxusReferralError):
        mark_warm_referral_ready(referral)


def test_warm_referral_requires_real_contact():
    referral = base_referral(contact_communicated=False)

    with pytest.raises(PaxusReferralError):
        mark_warm_referral_ready(referral)


def test_submission_requires_warm_referral():
    referral = base_referral()

    with pytest.raises(PaxusReferralError):
        submit_referral(referral)


def test_acceptance_requires_submission():
    referral = base_referral()

    with pytest.raises(PaxusReferralError):
        accept_referral(referral, "REF-001")


def test_acceptance_requires_referral_id():
    referral = submit_referral(
        mark_warm_referral_ready(
            base_referral()
        )
    )

    with pytest.raises(PaxusReferralError):
        accept_referral(referral, "")


def test_referral_id_is_recorded_on_acceptance():
    referral = submit_referral(
        mark_warm_referral_ready(
            base_referral()
        )
    )

    accepted = accept_referral(
        referral,
        "REF-001",
    )

    assert accepted.paxus_accepted is True
    assert accepted.referral_id == "REF-001"
    assert accepted.introduction_deadline is not None


def test_introduction_requires_acceptance():
    referral = submit_referral(
        mark_warm_referral_ready(
            base_referral()
        )
    )

    with pytest.raises(PaxusReferralError):
        mark_introduction_made(referral)


def test_full_paxus_referral_path():
    referral = base_referral()

    referral = mark_warm_referral_ready(referral)
    referral = submit_referral(referral)
    referral = accept_referral(referral, "REF-001")
    referral = mark_introduction_made(referral)

    assert can_deliver_to_paxus(referral) is True


def test_submission_does_not_equal_acceptance():
    referral = submit_referral(
        mark_warm_referral_ready(
            base_referral()
        )
    )

    assert referral.referral_submitted is True
    assert referral.paxus_accepted is False
    assert can_deliver_to_paxus(referral) is False


def test_acceptance_does_not_equal_introduction():
    referral = accept_referral(
        submit_referral(
            mark_warm_referral_ready(
                base_referral()
            )
        ),
        "REF-001",
    )

    assert referral.paxus_accepted is True
    assert referral.introduction_made is False
    assert can_deliver_to_paxus(referral) is False


def test_placement_requires_introduction():
    referral = accept_referral(
        submit_referral(
            mark_warm_referral_ready(
                base_referral()
            )
        ),
        "REF-001",
    )

    with pytest.raises(PaxusReferralError):
        record_placement(referral)


def test_client_payment_requires_placement():
    referral = accept_referral(
        submit_referral(
            mark_warm_referral_ready(
                base_referral()
            )
        ),
        "REF-001",
    )

    referral = mark_introduction_made(referral)

    with pytest.raises(PaxusReferralError):
        record_client_payment(referral)


def test_multiple_placements_are_allowed():
    referral = accept_referral(
        submit_referral(
            mark_warm_referral_ready(
                base_referral()
            )
        ),
        "REF-001",
    )

    referral = mark_introduction_made(referral)

    referral = record_placement(referral)
    referral = record_placement(referral)
    referral = record_placement(referral)
    referral = record_placement(referral)

    assert referral.placement_count == 4


def test_client_payment_makes_commission_due():
    referral = accept_referral(
        submit_referral(
            mark_warm_referral_ready(
                base_referral()
            )
        ),
        "REF-001",
    )

    referral = mark_introduction_made(referral)
    referral = record_placement(referral)
    referral = record_client_payment(referral)

    assert referral.client_payment_received is True
    assert referral.commission_due is True
