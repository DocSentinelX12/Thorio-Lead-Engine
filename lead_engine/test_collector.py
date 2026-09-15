import pytest

from .collector import collect, normalize_lead_input


def test_collector_normalizes_lead():
    lead = {
        "source": " linkedin ",
        "source_id": " lead-001 ",
        "url": " https://example.com/jobs/001 ",
        "company": " Acme ",
        "signal": " remote software engineer ",
        "evidence": " Hiring announcement ",
    }

    result = normalize_lead_input(lead)

    assert result["source"] == "linkedin"
    assert result["source_id"] == "lead-001"
    assert result["company"] == "Acme"
    assert result["signal"] == "remote software engineer"


def test_collector_preserves_company_website_for_public_research():
    lead = {
        "source": "company-site",
        "source_id": "lead-website-001",
        "url": "https://jobs.example.com/roles/001",
        "company": "Acme",
        "signal": "engineering expansion",
        "evidence": "Hiring announcement",
        "company_website": "https://acme.example.com",
    }

    result = normalize_lead_input(lead)

    assert result["company_website"] == "https://acme.example.com"
    assert result["website"] == "https://acme.example.com"


def test_collector_does_not_overwrite_explicit_website():
    lead = {
        "source": "company-site",
        "source_id": "lead-website-002",
        "url": "https://jobs.example.com/roles/002",
        "company": "Acme",
        "signal": "engineering expansion",
        "evidence": "Hiring announcement",
        "company_website": "https://acme.example.com",
        "website": "https://www.acme.example.com",
    }

    result = normalize_lead_input(lead)

    assert result["website"] == "https://www.acme.example.com"


def test_collector_rejects_incomplete_lead():
    lead = {
        "source": "linkedin",
        "source_id": "lead-002",
        "url": "https://example.com/jobs/002",
        "company": "Acme",
    }

    with pytest.raises(ValueError):
        collect([lead])


def test_collector_handles_multiple_leads():
    leads = [
        {
            "source": "linkedin",
            "source_id": "lead-001",
            "url": "https://example.com/jobs/001",
            "company": "Acme",
            "signal": "remote developer",
            "evidence": "Hiring developer",
        },
        {
            "source": "company-site",
            "source_id": "lead-002",
            "url": "https://example.com/jobs/002",
            "company": "Example Corp",
            "signal": "software engineer",
            "evidence": "Engineering opening",
        },
    ]

    result = collect(leads)

    assert len(result) == 2
    assert result[0]["company"] == "Acme"
    assert result[1]["company"] == "Example Corp"
