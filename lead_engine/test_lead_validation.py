from .lead_validation import (
    is_valid_lead,
    validate_lead,
)


def make_lead():
    return {
        "source": "linkedin",
        "source_id": "123",
        "url": "https://example.com/job/123",
        "company": "Acme",
        "signal": "remote software engineer",
        "evidence": "Acme is hiring a remote software engineer.",
    }


def test_valid_lead_has_no_errors():
    lead = make_lead()

    assert validate_lead(lead) == []


def test_valid_lead_returns_true():
    assert is_valid_lead(make_lead())


def test_missing_required_field_is_reported():
    lead = make_lead()
    del lead["company"]

    errors = validate_lead(lead)

    assert "missing_company" in errors


def test_blank_required_field_is_reported():
    lead = make_lead()
    lead["company"] = "   "

    errors = validate_lead(lead)

    assert "missing_company" in errors


def test_none_required_field_is_reported():
    lead = make_lead()
    lead["signal"] = None

    errors = validate_lead(lead)

    assert "missing_signal" in errors


def test_multiple_missing_fields_are_reported():
    lead = make_lead()
    lead["source"] = ""
    lead["company"] = ""
    lead["evidence"] = ""

    errors = validate_lead(lead)

    assert errors == [
        "missing_source",
        "missing_company",
        "missing_evidence",
    ]


def test_invalid_lead_returns_false():
    lead = make_lead()
    lead["url"] = ""

    assert not is_valid_lead(lead)


def test_extra_fields_do_not_make_lead_invalid():
    lead = make_lead()
    lead["custom_field"] = "anything"

    assert is_valid_lead(lead)
