from __future__ import annotations

from datetime import datetime, timezone


def test_research_upgrade_collects_public_web_and_preserves_unknowns(monkeypatch):
    from lead_engine import agent_workers

    captured = {}

    def fake_public_research(lead):
        captured["fingerprint"] = lead["fingerprint"]
        return {
            "status": "evidence_found",
            "research_method": "public_web_http",
            "sources": [{"url": "https://example.test/about", "status": "collected"}],
            "facts": {
                "company": [{"evidence": "Example company context", "url": "https://example.test/about"}],
                "decision_maker": [],
                "business_need": [{"evidence": "Example is expanding its engineering team", "url": "https://example.test/careers"}],
            },
        }

    monkeypatch.setattr("lead_engine.public_research.research_public_web", fake_public_research)

    class DB:
        def __init__(self):
            self.payload = {
                "fingerprint": "test-research-fingerprint",
                "company": "Example",
                "person": "Jane Example",
                "signal": "Hiring software engineers",
                "research_status": "research_required",
            }
            self.enqueued = []

        def update_payload(self, fingerprint, payload):
            assert fingerprint == self.payload["fingerprint"]
            self.payload = dict(payload)
            return dict(self.payload)

        def get(self, fingerprint):
            return dict(self.payload) if fingerprint == self.payload["fingerprint"] else None

    db = DB()
    ctx = agent_workers.AgentExecutionContext(db=db, worker_id="test")
    handler = agent_workers._PROCESSORS["company_research"]
    result = handler("company_research", {"lead": dict(db.payload), "evidence_events": []}, ctx)

    assert captured["fingerprint"] == "test-research-fingerprint"
    assert result["research"]["public_web_research"]["status"] == "evidence_found"
    assert result["research"]["public_decision_maker_facts"] == []
    assert result["research_status"] == "research_required"
    assert result["fabricated_fields"] == []


def test_research_aware_closer_uses_verified_research_without_inventing_facts():
    from lead_engine.outreach_engine import build_outreach_decision

    lead = {
        "fingerprint": "test-sales-fingerprint",
        "company": "Example",
        "contact_name": "Jane Example",
        "contact_email": "jane@example.test",
        "research_status": "complete",
        "potential_routes": ["Shiftr"],
        "signal": "The team is hiring engineers",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Jane Example",
            "decision_maker_evidence": "Public company leadership page identifies Jane Example.",
            "decision_maker_role_evidence": "Jane Example is CTO.",
            "decision_maker_verification_status": "verified",
            "business_context": "The company is expanding its engineering team.",
            "fabricated_fields": [],
        },
    }

    decision = build_outreach_decision(lead, now=datetime(2026, 9, 13, tzinfo=timezone.utc))

    assert "Jane Example" in decision.body
    assert "expanding its engineering team" in decision.body
    assert "CTO" in decision.body
    assert "generic pitch" in decision.body
    assert "invent" not in decision.body.lower()
