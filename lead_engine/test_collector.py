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


def test_universal_commercial_extraction_applies_to_generic_discovery_records():
    lead = {
        "source": "linkedin_signal",
        "source_id": "discovery-commercial-001",
        "url": "https://example.com/posts/001",
        "company": "Acme",
        "signal": "Founder announcement",
        "evidence": "We recently raised Series A and are looking for a development partner.",
        "signal_type": "business_intent",
    }

    result = normalize_lead_input(lead)

    assert result["signal_type"] == "commercial_intent"
    assert result["signal_strength"] == "compound"
    assert result["signal_matches"] == ["looking for a development partner", "raised series a"]
    assert result["signal_context"]
    assert "development partner" in result["signal_context"][0].lower()


def test_universal_commercial_extraction_preserves_hiring_without_commercial_evidence():
    lead = {
        "source": "job-board",
        "source_id": "job-001",
        "url": "https://example.com/jobs/001",
        "company": "Acme",
        "signal": "Senior Software Engineer",
        "evidence": "Acme is hiring a senior software engineer for its platform team.",
        "signal_type": "hiring",
    }

    result = normalize_lead_input(lead)

    assert result["signal_type"] == "hiring"
    assert "signal_matches" not in result
    assert "signal_context" not in result


def test_universal_commercial_extraction_scans_all_observed_fields():
    lead = {
        "source": "product-hunt",
        "source_id": "product-001",
        "url": "https://example.com/product/001",
        "company": "Acme",
        "signal": "Product launch",
        "evidence": "The team announced a new product launch.",
        "job_title": "Looking to build an MVP",
        "signal_type": "business_intent",
    }

    result = normalize_lead_input(lead)

    assert result["signal_type"] == "commercial_intent"
    assert "looking to build an mvp" in result["signal_matches"]
    assert "new product launch" in result["signal_matches"]


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
