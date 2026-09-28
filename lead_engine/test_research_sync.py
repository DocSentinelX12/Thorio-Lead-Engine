def test_sync_research_uses_atomic_upsert_when_lookup_is_empty(monkeypatch):
    lead = _complete_lead("research-race")
    captured = {}
    raced = {"id": "recResearchRace", "fields": {"Research Key": "research-race"}}
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app12345678901234")
    monkeypatch.setenv("AIRTABLE_RESEARCH_TABLE", "Research")
    monkeypatch.setenv("AIRTABLE_API_KEY", "test-api-key")
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
    assert captured["payload"]["records"][0]["fields"]["Research Key"] == "research-race"
