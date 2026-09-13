from __future__ import annotations

from types import SimpleNamespace

from lead_engine import advanced_agent_logic


def test_company_research_persists_public_evidence_without_fabrication(monkeypatch):
    lead = {
        "fingerprint": "test-public-research-1",
        "company": "Observed Company",
        "website": "https://observed.example/",
        "signal": "Observed need for engineering support",
        "evidence": "Observed source evidence",
    }
    captured = {}

    monkeypatch.setattr(
        advanced_agent_logic,
        "research_public_web",
        lambda value: {
            "status": "evidence_found",
            "researched_at": "2026-09-13T00:00:00+00:00",
            "sources": [{"url": "https://observed.example/", "observed_at": "2026-09-13T00:00:00+00:00", "status": "collected"}],
            "facts": {"company": [{"url": "https://observed.example/", "evidence": "Observed public company page"}]},
            "fabricated_fields": [],
        },
    )

    class DB:
        def update_payload(self, fingerprint, updates):
            captured["fingerprint"] = fingerprint
            captured["updates"] = updates
            return {**lead, **updates}

        def get(self, fingerprint):
            return lead if fingerprint == lead["fingerprint"] else None

        def enqueue(self, *args, **kwargs):
            return None

    monkeypatch.setattr(advanced_agent_logic, "enqueue", lambda *args, **kwargs: None)
    result = advanced_agent_logic.company_research(lead, SimpleNamespace(db=DB()))
    assert result["research_status"] == "research_required"
    assert result["public_research_status"] == "evidence_found"
    assert result["research"]["public_web_sources"][0]["url"] == "https://observed.example/"
    assert result["research"]["public_company_facts"][0]["evidence"] == "Observed public company page"
    assert result["research"]["fabricated_fields"] == []
    assert captured["updates"]["research_verified_fields"]
