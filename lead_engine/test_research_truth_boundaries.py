from __future__ import annotations

from types import SimpleNamespace

from lead_engine import advanced_agent_logic, public_research


def test_company_research_does_not_promote_signal_to_research(monkeypatch):
    lead = {
        "fingerprint": "truth-boundary-1",
        "company": "Observed Company",
        "website": "https://observed.example/",
        "signal": "SIGNAL TEXT MUST NOT BECOME RESEARCH",
        "evidence": "SOURCE EVIDENCE MUST NOT BECOME RESEARCH",
    }
    captured = {}

    monkeypatch.setattr(
        advanced_agent_logic,
        "research_public_web",
        lambda value: {
            "status": "evidence_found",
            "researched_at": "2026-09-13T00:00:00+00:00",
            "sources": [{"url": "https://observed.example/", "status": "collected"}],
            "facts": {"company": [{"url": "https://observed.example/", "evidence": "Observed company evidence", "verification_status": "observed_evidence"}]},
            "verified_fields": [],
            "fabricated_fields": [],
        },
    )

    class DB:
        def update_payload(self, fingerprint, updates):
            captured["updates"] = updates
            return {**lead, **updates}

    result = advanced_agent_logic.company_research(lead, SimpleNamespace(db=DB()))
    research = result["research"]
    assert research["observed_input"]["signal"] == lead["signal"]
    assert research["observed_input"]["evidence"] == lead["evidence"]
    assert research.get("business_context") in (None, "")
    assert research.get("current_need_evidence") in (None, "")
    assert lead["signal"] not in research.get("research_verified_fields", [])
    assert "observed_input" not in captured["updates"]["research_verified_fields"]
    assert result["research_status"] == "research_required"


def test_public_research_never_uses_third_party_source_domain_as_company_domain(monkeypatch):
    lead = {
        "company": "Example Company",
        "website": "https://example.com/",
        "source_url": "https://third-party.example/jobs/example-company-role",
    }
    assert all("third-party.example" not in url for url in public_research._candidate_urls(lead))
    assert any("example.com" in url for url in public_research._candidate_urls(lead))


def test_public_research_marks_keyword_classification_as_observed_evidence_not_verified_fact():
    pages = [
        {
            "status": "collected",
            "url": "https://example.com/",
            "observed_at": "2026-09-13T00:00:00+00:00",
            "facts": [{"field": "page_text", "value": "Our company is hiring engineers and our CTO leads the team."}],
        }
    ]
    classified = public_research._classify(pages)
    for category_items in classified.values():
        for item in category_items:
            assert item["verification_status"] == "observed_evidence"
