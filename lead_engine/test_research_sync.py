import json

from .research_sync import _research_payload, sync_research


def test_research_payload_preserves_research_and_raw_lead():
    lead = {
        "fingerprint": "research-test-1",
        "company": "Acme",
        "research_status": "complete",
        "research_verified_fields": ["company_verified", "decision_maker"],
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
        },
        "business_need_research": {"need": "engineering expansion", "verified": True, "verification_status": "verified"},
        "evidence_events": [{"source": "https://example.com", "observed_at": "2026-09-13"}],
        "unknown_field": "must survive in raw package",
    }

    fields = _research_payload(lead)

    assert fields["Research Key"] == "research-test-1"
    assert fields["Company"] == "Acme"
    assert fields["Research Status"] == "complete"
    assert json.loads(fields["Verified Fields"]) == ["company_verified", "decision_maker", "business_need_research"]
    assert json.loads(fields["Company Research"])["decision_maker"] == "Taylor"
    assert json.loads(fields["Evidence and Provenance"])[0]["source"] == "https://example.com"
    raw = json.loads(fields["Raw Research Package"])
    assert raw["unknown_field"] == "must survive in raw package"


def test_sync_research_updates_existing_record_without_dropping_fields(monkeypatch):
    lead = {
        "fingerprint": "research-test-2",
        "company": "Acme",
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
        },
    }
    existing = [{"id": "recResearch"}]
    updated = {"records": [{"id": "recResearch", "fields": {"Research Key": "research-test-2"}}]}

    monkeypatch.setattr("lead_engine.research_sync.find_master_records", lambda *args: existing)
    monkeypatch.setattr("lead_engine.research_sync.update_master_record", lambda *args: updated)

    result = sync_research(lead)

    assert result["status"] == "updated"
    assert result["record"]["id"] == "recResearch"


def test_sync_research_creates_missing_record(monkeypatch):
    lead = {
        "fingerprint": "research-test-3",
        "company": "Acme",
        "research_status": "research_required",
    }
    created = {"records": [{"id": "recNew", "fields": {"Research Key": "research-test-3"}}]}

    monkeypatch.setattr("lead_engine.research_sync.find_master_records", lambda *args: [])
    monkeypatch.setattr("lead_engine.research_sync.create_master_record", lambda *args: created)

    result = sync_research(lead)

    assert result["status"] == "created"
    assert result["record"]["id"] == "recNew"


def test_sync_research_rejects_missing_fingerprint():
    try:
        sync_research({"company": "Acme"})
    except ValueError as exc:
        assert "fingerprint" in str(exc).lower()
    else:
        raise AssertionError("Expected missing fingerprint to be rejected")
