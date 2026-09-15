from __future__ import annotations

from typing import Any

from . import public_research


def test_hiring_research_uses_exact_opportunity_url_not_source_listing(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_candidates(lead):
        captured.update(lead)
        return [lead["source_url"]]

    def fake_fetch(url):
        return {
            "url": url,
            "status": "collected",
            "observed_at": "2026-09-15T00:00:00+00:00",
            "facts": [
                {
                    "field": "page_text",
                    "value": "Radical I/O Technology Inc. QA Engineer",
                    "evidence_url": url,
                }
            ],
            "links": [],
        }

    monkeypatch.setattr(public_research, "_candidate_urls", fake_candidates)
    monkeypatch.setattr(public_research, "_fetch", fake_fetch)

    result = public_research.research_public_web(
        {
            "company": "Radical I/O Technology Inc.",
            "signal_type": "hiring",
            "url": "https://remotejobs.org/jobs/radical-io-qa-engineer",
            "source_url": "https://remotejobs.org/api/v1/jobs?limit=50&offset=0",
        }
    )

    assert captured["source_url"] == "https://remotejobs.org/jobs/radical-io-qa-engineer"
    assert result["status"] == "evidence_found"
    assert result["company_identity_match_count"] == 1


def test_hiring_research_rejects_evidence_for_different_company(monkeypatch):
    monkeypatch.setattr(
        public_research,
        "_candidate_urls",
        lambda lead: [lead["source_url"]],
    )
    monkeypatch.setattr(
        public_research,
        "_fetch",
        lambda url: {
            "url": url,
            "status": "collected",
            "observed_at": "2026-09-15T00:00:00+00:00",
            "facts": [
                {
                    "field": "page_text",
                    "value": "ThermalWorks Field Service Technician HVAC data centers",
                    "evidence_url": url,
                }
            ],
            "links": [],
        },
    )

    result = public_research.research_public_web(
        {
            "company": "Radical I/O Technology Inc.",
            "signal_type": "hiring",
            "url": "https://example.com/radical-io-qa-engineer",
            "source_url": "https://example.com/radical-io-qa-engineer",
        }
    )

    assert result["status"] == "no_company_matched_evidence"
    assert result["pages_collected"] == 0
    assert all(not values for values in result["facts"].values())
    assert result["rejected_page_count"] == 1
    assert result["raw_pages"][0]["evidence_admission_status"] == "rejected_company_identity_mismatch"


def test_hiring_research_blocks_listing_or_api_without_exact_opportunity_url():
    result = public_research.research_public_web(
        {
            "company": "ThermalWorks",
            "signal_type": "hiring",
            "source_url": "https://remotejobs.org/api/v1/jobs?limit=50&offset=0",
        }
    )

    assert result["status"] == "no_exact_opportunity_url"
    assert result["pages_attempted"] == 0
    assert result["pages_collected"] == 0
    assert result["identity_gate"] == "blocked_without_exact_opportunity_url"
