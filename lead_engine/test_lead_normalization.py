from .lead_normalization import normalize_lead


def test_normalize_lead_trims_strings():
    lead = {
        "company": "  Acme  ",
        "signal": " remote software engineer ",
        "contact_name": " Jane Smith ",
        "contact_title": " CTO ",
        "contact_email": " jane@example.com ",
    }

    result = normalize_lead(lead)

    assert result["company"] == "Acme"
    assert result["signal"] == "remote software engineer"
    assert result["contact_name"] == "Jane Smith"
    assert result["contact_title"] == "CTO"
    assert result["contact_email"] == "jane@example.com"


def test_normalize_lead_preserves_non_string_fields():
    lead = {
        "company": " Acme ",
        "lead_score": 95,
        "potential_routes": ["Thorio"],
        "metadata": {"source": "test"},
    }

    result = normalize_lead(lead)

    assert result["lead_score"] == 95
    assert result["potential_routes"] == ["Thorio"]
    assert result["metadata"] == {"source": "test"}


def test_normalize_lead_preserves_unknown_fields():
    lead = {
        "company": " Acme ",
        "custom_field": "  custom value  ",
    }

    result = normalize_lead(lead)

    assert result["company"] == "Acme"
    assert result["custom_field"] == "  custom value  "


def test_normalize_lead_does_not_mutate_original():
    lead = {
        "company": "  Acme  ",
        "signal": "  engineer  ",
    }

    result = normalize_lead(lead)

    assert lead["company"] == "  Acme  "
    assert lead["signal"] == "  engineer  "
    assert result is not lead


def test_normalize_none_as_empty_string():
    lead = {
        "company": None,
        "person": None,
        "contact_email": None,
    }

    result = normalize_lead(lead)

    assert result["company"] == ""
    assert result["person"] == ""
    assert result["contact_email"] == ""
