from .lead_validation import (
    is_valid_lead,
    validate_lead,
    validation_result,
)


def make_lead():
    return {
        "source": "linkedin",
        "source_id": "lead-001",
        "url": "https://example.com/job/001",
        "company": "Acme",
        "signal": "remote software engineer",
        "evidence": "Acme is hiring a remote software engineer.",
    }


def test_valid_lead():
    lead = make_lead()

    assert validate_lead(lead) == []
    assert is_valid_lead(lead)


def test_missing_required_field():
    lead = make_lead()
    del lead["company"]

    errors = validate_lead(lead)

    assert "missing_company" in errors
    assert not is_valid_lead(lead)


def test_blank_required_field():
    lead = make_lead()
    lead["signal"] = "   "

    errors = validate_lead(lead)

    assert "missing_signal" in errors


def test_invalid_url():
    lead = make_lead()
    lead["url"] = "not-a-url"

    errors = validate_lead(lead)

    assert "invalid_url" in errors
    assert not is_valid_lead(lead)


def test_validation_result():
    lead = make_lead()

    result = validation_result(lead)

    assert result["valid"] is True
    assert result["errors"] == []


def test_validation_result_with_errors():
    lead = make_lead()
    lead["source_id"] = ""

    result = validation_result(lead)

    assert result["valid"] is False
    assert "missing_source_id" in result["errors"]


def test_validation_does_not_mutate_lead():
    lead = make_lead()

    original = dict(lead)

    validate_lead(lead)

    assert lead == original
