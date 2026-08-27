from .lead_quality import (
    filter_high_quality,
    is_high_quality,
    quality_score,
)


def make_lead():
    return {
        "company": "Acme",
        "source": "linkedin",
        "source_id": "123",
        "url": "https://example.com/job/123",
        "signal": "remote software engineer",
        "evidence": "Acme is hiring a remote software engineer.",
        "contact_email": "jane@example.com",
    }


def test_complete_lead_has_full_quality_score():
    assert quality_score(make_lead()) == 100.0


def test_empty_lead_has_zero_quality_score():
    assert quality_score({}) == 0.0


def test_partial_lead_quality_score():
    lead = {
        "company": "Acme",
        "source": "linkedin",
        "source_id": "123",
        "url": "",
        "signal": "",
        "evidence": "",
        "contact_email": "",
    }

    assert quality_score(lead) == 42.86


def test_high_quality_lead():
    assert is_high_quality(make_lead())


def test_low_quality_lead():
    assert not is_high_quality(
        {},
        minimum_score=70,
    )


def test_custom_quality_threshold():
    lead = {
        "company": "Acme",
        "source": "linkedin",
        "source_id": "123",
        "url": "",
        "signal": "",
        "evidence": "",
        "contact_email": "",
    }

    assert is_high_quality(
        lead,
        minimum_score=40,
    )


def test_filter_high_quality():
    good = make_lead()
    bad = {}

    result = filter_high_quality(
        [good, bad],
    )

    assert len(result) == 1
    assert result[0]["company"] == "Acme"


def test_filter_high_quality_accepts_generator():
    leads = (
        make_lead()
        for _ in range(3)
    )

    result = filter_high_quality(leads)

    assert len(result) == 3


def test_filter_high_quality_returns_copies():
    lead = make_lead()

    result = filter_high_quality([lead])

    assert result[0] == lead
    assert result[0] is not lead
