from .lead_fingerprint import (
    lead_fingerprint,
    same_lead,
)


def test_fingerprint_is_stable():
    lead = {
        "source": "linkedin",
        "source_id": "abc-123",
        "company": "Acme",
    }

    assert lead_fingerprint(lead) == lead_fingerprint(lead)


def test_same_source_identity_matches():
    first = {
        "source": "linkedin",
        "source_id": "abc-123",
        "company": "Acme",
    }

    second = {
        "source": "linkedin",
        "source_id": "abc-123",
        "company": "Different Name",
    }

    assert same_lead(first, second)


def test_different_source_identity_does_not_match():
    first = {
        "source": "linkedin",
        "source_id": "abc-123",
    }

    second = {
        "source": "linkedin",
        "source_id": "abc-456",
    }

    assert not same_lead(first, second)


def test_fallback_identity_matches():
    first = {
        "company": "  Acme  ",
        "person": " Jane Smith ",
        "url": "https://example.com/job/1",
        "signal": " Remote Engineer ",
    }

    second = {
        "company": "acme",
        "person": "jane smith",
        "url": "https://example.com/job/1",
        "signal": "remote engineer",
    }

    assert same_lead(first, second)


def test_fingerprint_is_sha256_length():
    lead = {
        "source": "test",
        "source_id": "123",
    }

    fingerprint = lead_fingerprint(lead)

    assert len(fingerprint) == 64
    assert all(
        character in "0123456789abcdef"
        for character in fingerprint
    )


def test_whitespace_and_case_do_not_change_identity():
    first = {
        "source": "LinkedIn",
        "source_id": " ABC-123 ",
    }

    second = {
        "source": "linkedin",
        "source_id": "abc-123",
    }

    assert same_lead(first, second)


def test_fingerprint_uses_canonical_lead_identity():
    first = {
        "source": "linkedin",
        "source_id": "ABC-123",
        "company": "Acme",
        "route": "Thorio",
    }

    second = {
        "source": "linkedin",
        "source_id": "ABC-123",
        "company": "Different Company",
        "route": "Paxus",
    }

    assert lead_fingerprint(first) == lead_fingerprint(second)
