"""Regression coverage for durable, fair bounded Airtable backlog draining."""
from unittest.mock import patch

from .airtable_drain_override import drain_pending
from .database import LeadDB


def test_deferred_leads_are_not_reprocessed_or_dropped_within_one_drain_cycle(tmp_path, monkeypatch):
    db = LeadDB(data_dir=tmp_path)
    total = 125
    for index in range(total):
        fingerprint = f"deferred-{index:03d}"
        assert db.insert_if_new({
            "fingerprint": fingerprint,
            "company": f"Company {index}",
            "source": "test",
            "source_id": fingerprint,
            "url": f"https://example.com/{fingerprint}",
            "signal": "Current technology hiring signal",
            "evidence": "Observed public hiring signal",
            "potential_routes": ["Thorio"],
            "qualified": False,
        })

    monkeypatch.setenv("THORIO_AIRTABLE_DRAIN_SECONDS", "3")
    ticks = iter((0.0, 1.0, 2.0, 3.0))
    monkeypatch.setattr("lead_engine.airtable_drain_override.time.perf_counter", lambda: next(ticks))

    with patch("lead_engine.batch_delivery._run_batch_high_volume_sync"), patch(
        "lead_engine.batch_delivery.package_is_ready", return_value=False
    ):
        result = drain_pending(db)

    deferred_fingerprints = {
        item["lead"]["fingerprint"]
        for item in result["deferred_research"]
        if isinstance(item, dict) and isinstance(item.get("lead"), dict)
    }
    assert result["batches"] == 3
    assert result["deferred_research_count"] == total
    assert len(deferred_fingerprints) == total
    assert result["drain_complete"] is False
    assert len(db.pending(limit=total + 1)) == total
    assert result["failed_count"] == 0



def test_drain_accepts_the_scheduler_supplied_batch_delivery_callable(tmp_path, monkeypatch):
    from . import batch_delivery

    db = LeadDB(data_dir=tmp_path)
    fingerprint = "explicit-batch-callable"
    assert db.insert_if_new({
        "fingerprint": fingerprint,
        "company": "Example Corp",
        "source": "test",
        "source_id": fingerprint,
        "url": "https://example.com/jobs/role",
        "signal": "Current technology hiring signal",
        "evidence": "Observed public hiring signal",
        "potential_routes": ["Thorio"],
        "qualified": False,
    })
    monkeypatch.setenv("THORIO_AIRTABLE_DRAIN_SECONDS", "1")

    with patch("lead_engine.batch_delivery._run_batch_high_volume_sync"), patch(
        "lead_engine.batch_delivery.package_is_ready", return_value=False
    ):
        result = drain_pending(db, sync_batch=batch_delivery.sync_pending_batched)

    assert result["deferred_research_count"] == 1
    assert result["drain_complete"] is False
    assert len(db.pending(limit=10)) == 1


 
def test_transient_airtable_failure_does_not_fan_out_into_single_record_retries(tmp_path, monkeypatch):
    from .airtable_sync import AirtableTransientError

    db = LeadDB(data_dir=tmp_path)
    fingerprint = "transient-airtable-failure"
    lead = {
        "fingerprint": fingerprint,
        "company": "Example Corp",
        "source": "test",
        "source_id": fingerprint,
        "url": "https://example.com/jobs/role",
        "signal": "Current technology hiring signal",
        "evidence": "Observed public hiring signal",
        "potential_routes": ["Thorio"],
        "qualified": False,
    }
    assert db.insert_if_new(lead)
    monkeypatch.setenv("THORIO_AIRTABLE_DRAIN_SECONDS", "2")

    with patch("lead_engine.batch_delivery._run_batch_high_volume_sync", side_effect=AirtableTransientError("Airtable request exceeded its absolute deadline")), patch(
        "lead_engine.sync_worker.sync_one", side_effect=AssertionError("transient failure must not trigger per-record fallback")
    ):
        result = drain_pending(db)

    assert result["failed_count"] == 1
    assert result["failed"][0]["lead"]["fingerprint"] == fingerprint
    assert len(db.pending(limit=10)) == 1
