from unittest.mock import patch

from .batch_delivery import _run_batch_high_volume_sync, sync_pending_batched
from .database import LeadDB


def _lead(fingerprint: str, company: str = "Example Corp"):
    return {
        "fingerprint": fingerprint,
        "company": company,
        "source": "x",
        "url": f"https://example.com/{fingerprint}",
        "signal": "Hiring remote software engineer",
        "evidence": "Current engineering hiring signal.",
        "potential_routes": ["Shiftr", "Thorio"],
        "qualified": False,
        "lead_score": 70,
        "priority": "Warm",
    }


def test_high_volume_delivery_uses_airtable_batches():
    leads = [_lead("batch-001"), _lead("batch-002", "Second Corp")]

    with patch("lead_engine.batch_delivery._batch_upsert") as mock_batch:
        mock_batch.side_effect = lambda table, merge, records: records
        _run_batch_high_volume_sync(leads)

    calls = mock_batch.call_args_list
    assert [call.args[0] for call in calls] == ["lead_radar", "companies"]
    assert [call.args[1] for call in calls] == ["Duplicate Key", "Company"]
    assert all(len(call.args[2]) <= 10 for call in calls)


def test_batch_delivery_marks_local_state_only_after_all_downstream_work_succeeds(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    lead = _lead("batch-retry-001")
    assert db.insert_if_new(lead)

    with patch("lead_engine.batch_delivery._run_batch_high_volume_sync") as mock_batch, \
         patch("lead_engine.batch_delivery.sync_outreach"), \
         patch("lead_engine.batch_delivery.sync_followup"), \
         patch("lead_engine.batch_delivery.sync_paxus_referral_state"), \
         patch("lead_engine.batch_delivery.sync_commission", return_value=None):
        mock_batch.return_value = None
        result = sync_pending_batched(db, limit=10)

    assert result["failed_count"] == 0
    assert result["synced_count"] == 1
    assert db.get_sync_state("batch-retry-001")["synced"] is True


def test_batch_delivery_falls_back_to_single_record_sync_on_batch_failure(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    lead = _lead("batch-fallback-001")
    assert db.insert_if_new(lead)

    fallback_result = {
        "status": "synced",
        "lead": lead,
        "airtable_record": {"id": "rec_fallback"},
        "error": None,
    }

    with patch("lead_engine.batch_delivery._run_batch_high_volume_sync", side_effect=RuntimeError("batch rejected")), \
         patch("lead_engine.sync_worker.sync_one", return_value=fallback_result) as mock_single:
        result = sync_pending_batched(db, limit=10)

    assert result["synced_count"] == 1
    assert result["failed_count"] == 0
    mock_single.assert_called_once_with(lead)
    assert db.get_sync_state("batch-fallback-001")["synced"] is True
