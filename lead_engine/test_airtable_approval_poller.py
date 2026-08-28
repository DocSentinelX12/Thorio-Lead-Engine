from unittest.mock import Mock

from lead_engine.airtable_approval_poller import (
    AirtableApprovalPoller,
)
from lead_engine.database import LeadDB


def test_poller_runs_multiple_cycles(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path),
    )

    fetch_pending = Mock(
        return_value=[],
    )

    poller = AirtableApprovalPoller(
        db=db,
        fetch_pending=fetch_pending,
        interval_seconds=1,
    )

    results = poller.run(
        max_cycles=3,
        sleep=lambda _: None,
    )

    assert len(results) == 3
    assert fetch_pending.call_count == 3
    assert poller.running is False

    for result in results:
        assert result["approved_count"] == 0
        assert result["pending_count"] == 0
        assert result["rejected_count"] == 0

    db.conn.close()


def test_poller_survives_airtable_failure(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path),
    )

    fetch_pending = Mock(
        side_effect=Exception(
            "Airtable temporarily unavailable"
        ),
    )

    poller = AirtableApprovalPoller(
        db=db,
        fetch_pending=fetch_pending,
        interval_seconds=1,
    )

    results = poller.run(
        max_cycles=2,
        sleep=lambda _: None,
    )

    assert len(results) == 2

    for result in results:
        assert result["status"] == "failed"
        assert (
            result["error"]
            == "Airtable temporarily unavailable"
        )

    assert poller.running is False

    db.conn.close()


def test_poller_can_be_stopped(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path),
    )

    poller = AirtableApprovalPoller(
        db=db,
        fetch_pending=lambda: [],
        interval_seconds=1,
    )

    poller.running = True
    poller.stop()

    assert poller.running is False

    db.conn.close()
