from .enrichment import (
    enrich_lead,
    has_contact_information,
)


def test_enrichment_preserves_existing_lead_data():
    lead = {
        "company": "Acme",
        "signal": "remote software engineer",
        "route": "Thorio",
        "lead_score": 12,
        "contact_name": " Jane Smith ",
        "contact_title": " CTO ",
        "contact_email": " jane@example.com ",
    }

    result = enrich_lead(lead)

    assert result["company"] == "Acme"
    assert result["signal"] == "remote software engineer"
    assert result["route"] == "Thorio"
    assert result["lead_score"] == 12

    assert result["contact_name"] == "Jane Smith"
    assert result["contact_title"] == "CTO"
    assert result["contact_email"] == "jane@example.com"
    assert result["enrichment_status"] == "enriched"


def test_enrichment_does_not_invent_contact_information():
    lead = {
        "company": "Acme",
        "signal": "remote software engineer",
        "route": "Thorio",
    }

    result = enrich_lead(lead)

    assert result["contact_name"] == ""
    assert result["contact_title"] == ""
    assert result["contact_email"] == ""
    assert result["contact_phone"] == ""
    assert result["linkedin_url"] == ""
    assert result["company_website"] == ""
    assert result["enrichment_status"] == "pending"


def test_enrichment_handles_missing_values():
    lead = {
        "company": "Acme",
        "contact_name": None,
        "contact_email": None,
        "linkedin_url": None,
    }

    result = enrich_lead(lead)

    assert result["contact_name"] == ""
    assert result["contact_email"] == ""
    assert result["linkedin_url"] == ""
    assert result["enrichment_status"] == "pending"


def test_has_contact_information_detects_contact():
    lead = {
        "company": "Acme",
        "contact_email": "cto@example.com",
    }

    assert has_contact_information(lead) is True


def test_has_contact_information_returns_false_without_contact():
    lead = {
        "company": "Acme",
        "signal": "remote software engineer",
    }

    assert has_contact_information(lead) is False
