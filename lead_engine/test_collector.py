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
