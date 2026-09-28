def test_quarantined_lead_requires_deliberate_requeue_and_gets_a_fresh_bounded_cycle(tmp_path):
    from .database import LeadDB
    from .retry_policy import DEFAULT_MAX_ATTEMPTS
    import pytest
    db = LeadDB(data_dir=str(tmp_path))
    lead = {"fingerprint": "quarantine-requeue-001", "company": "Recovery Corp"}
    assert db.insert_if_new(lead)
    for index in range(DEFAULT_MAX_ATTEMPTS - 1):
        result = db.mark_error(lead["fingerprint"], f"failure-{index + 1}")
    assert result["quarantined"] is False
    with pytest.raises(ValueError, match="not quarantined"):
        db.requeue_quarantined(lead["fingerprint"], "should not be early")
    result = db.mark_error(lead["fingerprint"], f"failure-{DEFAULT_MAX_ATTEMPTS}")
    assert result["quarantined"] is True
    assert db.pending(limit=50) == []
    state = db.requeue_quarantined(lead["fingerprint"], "operator verified Airtable availability")
    assert state["synced"] is False
    assert state["attempts"] == 0
    assert "Quarantine requeued:" in state["last_error"]
    assert len(db.pending(limit=50)) == 1
