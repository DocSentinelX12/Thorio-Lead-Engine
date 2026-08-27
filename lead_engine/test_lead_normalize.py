from .lead_normalize import normalize_lead


def test_normalize_strips_text_fields():
    lead = {
        "company": " Acme ",
        "contact_name": " Jane Smith ",
        "contact_title": " CTO ",
        "signal": " remote software engineer ",
    }

    result = normalize_lead(lead)

    assert result["company"] == "Acme"
    assert result["contact_name"] == "Jane Smith"
    assert result["contact_title"] == "CTO"
    assert result["signal"] == "remote software engineer"


def test_normalize_email():
    lead = {
        "contact_email": " Jane@EXAMPLE.COM ",
    }

    result = normalize_lead(lead)

    assert result["contact_email"] == "jane@example.com"


def test_normalize_does_not_mutate_original():
    lead = {
        "company": " Acme ",
        "contact_email": " JANE@EXAMPLE.COM ",
    }

    result = normalize_lead(lead)

    assert lead["company"] == " Acme "
    assert lead["contact_email"] == " JANE@EXAMPLE.COM "
    assert result is not lead


def test_normalize_preserves_non_text_values():
    lead = {
        "company": " Acme ",
        "lead_score": 95,
        "metadata": {"source": "test"},
    }

    result = normalize_lead(lead)

    assert result["lead_score"] == 95
    assert result["metadata"] == {"source": "test"}


def test_normalize_preserves_unknown_fields():
    lead = {
        "company": " Acme ",
        "custom_field": " custom value ",
    }

    result = normalize_lead(lead)

    assert result["custom_field"] == " custom value "


def test_normalize_handles_missing_fields():
    lead = {
        "company": "Acme",
    }

    result = normalize_lead(lead)

    assert result["company"] == "Acme"
    assert "contact_email" not in result


def test_normalize_handles_none_values():
    lead = {
        "company": None,
        "contact_email": None,
    }

    result = normalize_lead(lead)

    assert result["company"] is None
    assert result["contact_email"] is None


def test_normalize_empty_lead():
    assert normalize_lead({}) == {}
