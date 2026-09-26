import json

from .research_sync import _research_payload, _research_table_url, sync_research


def test_research_payload_preserves_research_and_raw_lead():
    lead = {
        "fingerprint": "research-test-1",
        "company": "Acme",
        "research_status": "complete",
        "research_verified_fields": ["company_verified", "decision_maker"],
        "research_intelligence": {"intelligence_version": "1", "opportunity_id": "research-test-1", "claims": [], "evidence_graph": {"nodes": {}}},\n        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
        },
        "business_need_research": {"need": "engineering expansion", "verified": True, "verification_status": "verified"},
        "technical_product_hiring_research": {"need": "engineering expansion", "verified": True, "verification_status": "verified"},
        "evidence_events": [{"source": "https://example.com", "observed_at": "2026-09-13"}],
        "unknown_field": "must survive in raw package",
    }

    fields = _research_payload(lead)

    assert fields["Research Key"] == "research-test-1"
    assert fields["Company"] == "Acme"
    assert fields["Research Status"] == "complete"
    assert json.loads(fields["Verified Fields"]) == [
        "company_verified",
        "decision_maker",
        "business_need_research",
        "technical_product_hiring_research",
    ]
    assert json.loads(fields["Research Intelligence"])["intelligence_version"] == "1"\n    assert json.loads(fields["Company Research"])["decision_maker"] == "Taylor"
    assert "Technical/Product/Hiring Research" not in fields
    assert "Technical Product Hiring Research" in fields
    assert json.loads(fields["Technical Product Hiring Research"])["need"] == "engineering expansion"
    assert json.loads(fields["Evidence and Provenance"])[0]["source"] == "https://example.com"
    raw = json.loads(fields["Raw Research Package"])
    assert raw["unknown_field"] == "must survive in raw package"


def test_research_table_url_uses_dedicated_research_configuration(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app12345678901234")
    monkeypatch.setenv("AIRTABLE_RESEARCH_TABLE", "Research")
    assert _research_table_url() == "https://api.airtable.com/v0/app12345678901234/Research"


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


def test_research_payload_persists_canonical_opportunity_identity():
    import json
    from .research_sync import _research_payload

    lead = {
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "AI Engineer",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
        "business_need_research": {"verified": False, "verification_status": "observed_evidence", "evidence": []},
    }
    from .lead_identity import canonical_opportunity_identity
    identity = canonical_opportunity_identity(lead)
    lead.update({
        "opportunity_id": identity["opportunity_id"],
        "fingerprint": identity["fingerprint"],
        "identity_version": identity["identity_version"],
        "identity_derivation": identity["derivation"],
    })

    fields = _research_payload(lead)
    raw = json.loads(fields["Raw Research Package"])

    assert raw["opportunity_id"] == lead["fingerprint"]
    assert raw["fingerprint"] == lead["fingerprint"]
    assert raw["identity_version"] == "1"
    assert raw["identity_derivation"]["source_id"] == "post-1"


def test_research_payload_rejects_mismatched_opportunity_identity():
    import pytest
    from .research_sync import _research_payload

    with pytest.raises(ValueError, match="opportunity_id.*fingerprint"):
        _research_payload({"fingerprint": "opp-1", "opportunity_id": "opp-2", "company": "Acme"})
\n\ndef test_research_payload_rejects_mismatched_research_intelligence():\n    import pytest\n\n    with pytest.raises(ValueError, match="opportunity"):\n        _research_payload({\n            "fingerprint": "opp-1",\n            "opportunity_id": "opp-1",\n            "company": "Acme",\n            "research_intelligence": {"opportunity_id": "opp-2", "fingerprint": "opp-2", "claims": [], "evidence_graph": {"nodes": {}}},\n        })\n