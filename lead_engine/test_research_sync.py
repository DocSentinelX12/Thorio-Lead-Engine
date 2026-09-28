import json
import pytest

from .research_sync import _research_payload, _research_table_url, sync_research
from .research_intelligence import build_research_intelligence
from .lead_identity import canonical_opportunity_identity


def _complete_lead(fingerprint: str = "research-test") -> dict:
    lead = {
        "fingerprint": fingerprint,
        "opportunity_id": fingerprint,
        "source": "test",
        "source_id": fingerprint,
        "url": f"https://example.com/opportunities/{fingerprint}",
        "person": "Taylor",
        "job_title": "Software Engineer",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
        "company": "Acme",
        "contact_name": "Taylor",
        "contact_email": "taylor@example.com",
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
            "public_company_facts": [{"url": "https://example.com/about", "evidence": "Acme builds workflow software.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}],
        },
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "engineering expansion", "evidence": [{"url": "https://example.com/need", "evidence": "Acme needs engineering capacity for expansion.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "engineering expansion", "evidence": [{"url": "https://example.com/intent", "evidence": "Acme is actively hiring engineers.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/hiring", "evidence": "Acme has open backend engineering roles.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Acme sells enterprise workflow software.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "route_research": {"routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Engineering expansion is relevant to Thorio.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Acme needs engineering capacity for expansion.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}]},
        "potential_routes": ["Thorio"],
        "eligible_routes": ["Thorio"],
        "preserved_routes": ["Thorio"],
        "routing_result": {"destinations": ["Thorio"], "review_required": False},
        "evidence_events": [{"source": "https://example.com", "evidence": "Acme is actively hiring engineers.", "observed_at": "2026-09-26T00:00:00+00:00", "verification_status": "verified"}],
        "unknown_field": "must survive in raw package",
    }
    lead.update(canonical_opportunity_identity(lead))
    lead["research_intelligence"] = build_research_intelligence(lead)
    return lead


def test_research_payload_preserves_complete_research_and_raw_lead():
    fields = _research_payload(_complete_lead("research-test-1"))
    assert fields["Research Key"] == _complete_lead("research-test-1")["fingerprint"]
    assert fields["Company"] == "Acme"
    assert fields["Research Status"] == "complete"
    intelligence = json.loads(fields["Research Intelligence"])
    assert intelligence["claims"]
    assert intelligence["evidence_graph"]["nodes"]
    assert json.loads(fields["Company Research"])["decision_maker"] == "Taylor"
    assert "Technical Product Hiring Research" in fields
    assert json.loads(fields["Technical Product Hiring Research"])["evidence"]
    raw = json.loads(fields["Raw Research Package"])
    assert raw["unknown_field"] == "must survive in raw package"
    assert fields["Package Digest"] == raw["__thorio_package_digest"]


def test_research_table_url_uses_dedicated_research_configuration(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app12345678901234")
    monkeypatch.setenv("AIRTABLE_RESEARCH_TABLE", "Research")
    assert _research_table_url() == "https://api.airtable.com/v0/app12345678901234/Research"


def test_sync_research_updates_existing_complete_record_without_dropping_fields(monkeypatch):
    lead = _complete_lead("research-test-2")
    existing = [{"id": "recResearch"}]
    updated = {"records": [{"id": "recResearch", "fields": {"Research Key": "research-test-2"}}]}
    monkeypatch.setattr("lead_engine.research_sync.find_master_records", lambda *args: existing)
    monkeypatch.setattr("lead_engine.research_sync.update_master_record", lambda *args: updated)
    result = sync_research(lead)
    assert result["status"] == "updated"
    assert result["record"]["id"] == "recResearch"


def test_sync_research_rejects_incomplete_research_before_airtable(monkeypatch):
    lead = {"fingerprint": "research-test-3", "opportunity_id": "research-test-3", "company": "Acme", "source": "test", "source_id": "research-test-3", "url": "https://example.com/opportunities/research-test-3", "person": "Taylor", "job_title": "Software Engineer", "signal_type": "hiring", "discovered_at": "2026-09-26T00:00:00+00:00", "research_status": "research_required"}
    lead.update(canonical_opportunity_identity(lead))
    monkeypatch.setattr("lead_engine.research_sync.find_master_records", lambda *args: (_ for _ in ()).throw(AssertionError("Airtable lookup must not occur for incomplete research")))
    with pytest.raises(ValueError, match="Research intelligence"):
        sync_research(lead)


def test_sync_research_rejects_missing_fingerprint():
    with pytest.raises(ValueError, match="fingerprint"):
        sync_research({"company": "Acme"})


def test_research_payload_persists_canonical_opportunity_identity():
    lead = _complete_lead("canonical-identity")
    fields = _research_payload(lead)
    raw = json.loads(fields["Raw Research Package"])
    assert raw["opportunity_id"] == lead["opportunity_id"]
    assert raw["fingerprint"] == lead["fingerprint"]
    assert raw["identity_version"] == lead["identity_version"]
    assert raw["identity_derivation"] == lead["identity_derivation"]


def test_research_payload_rejects_mismatched_opportunity_identity():
    lead = _complete_lead("opp-1")
    lead["opportunity_id"] = "opp-2"
    with pytest.raises(ValueError, match="opportunity_id does not match canonical opportunity identity"):
        _research_payload(lead)


def test_research_payload_rejects_mismatched_research_intelligence():
    lead = _complete_lead("opp-1")
    lead["research_intelligence"]["opportunity_id"] = "opp-2"
    with pytest.raises(ValueError, match="opportunity"):
        _research_payload(lead)


def test_sync_research_uses_atomic_upsert_when_lookup_is_empty(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app12345678901234")
    monkeypatch.setenv("AIRTABLE_RESEARCH_TABLE", "Research")
    monkeypatch.setenv("AIRTABLE_API_KEY", "pat_test_fixture")
    lead = _complete_lead("research-race")
    captured = {}
    raced = {"id": "recResearchRace", "fields": {"Research Key": lead["fingerprint"]}}
    monkeypatch.setattr("lead_engine.research_sync.find_master_records", lambda *args: [])
    def fake_request(method, url, payload):
        captured.update(method=method, url=url, payload=payload)
        return {"records": [raced]}
    monkeypatch.setattr("lead_engine.research_sync._request", fake_request)
    result = sync_research(lead)
    assert result["status"] == "created"
    assert result["record"] == raced
    assert captured["method"] == "PATCH"
    assert captured["payload"]["performUpsert"]["fieldsToMergeOn"] == ["Research Key"]
    assert captured["payload"]["records"][0]["fields"]["Research Key"] == lead["fingerprint"]
