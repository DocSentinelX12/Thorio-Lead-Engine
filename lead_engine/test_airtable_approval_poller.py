from unittest.mock import Mock, patch

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


def test_poller_uses_real_airtable_candidate_fetch_by_default():
    from lead_engine.airtable_approval_poller import (
        AirtableApprovalPoller,
    )

    items = [
        {
            "record_id": "rec_1",
            "lead": {
                "company": "Candidate Corp",
            },
        }
    ]

    with patch(
        "lead_engine.airtable_approval_poller.fetch_approval_candidates",
        return_value=items,
    ) as fetch:
        with patch(
            "lead_engine.airtable_approval_poller.process_approval_batch",
            return_value={
                "approved": [],
                "pending": [],
                "rejected": [],
                "already_processed": [],
                "approved_count": 0,
                "pending_count": 0,
                "rejected_count": 0,
                "already_processed_count": 0,
            },
        ) as process:
            poller = AirtableApprovalPoller(
                db=None
            )

            result = poller.poll_once()

    fetch.assert_called_once()
    process.assert_called_once()

    assert result["approved_count"] == 0


def test_poller_still_supports_injected_fetcher():
    from lead_engine.airtable_approval_poller import (
        AirtableApprovalPoller,
    )

    items = [
        {
            "record_id": "rec_test",
            "lead": {
                "company": "Test Corp",
            },
        }
    ]

    fetcher = lambda: items

    with patch(
        "lead_engine.airtable_approval_poller.process_approval_batch",
        return_value={
            "approved": [],
            "pending": [],
            "rejected": [],
            "already_processed": [],
            "approved_count": 0,
            "pending_count": 0,
            "rejected_count": 0,
            "already_processed_count": 0,
        },
    ):
        poller = AirtableApprovalPoller(
            db=None,
            fetch_pending=fetcher,
        )

        poller.poll_once()

    assert poller.fetch_pending is fetcher


def test_poller_does_not_filter_out_previous_states():
    from lead_engine.airtable_approval import (
        fetch_approval_candidates,
    )

    records = [
        {
            "id": "rec_reviewing",
            "fields": {
                "Company": "Reviewing Corp",
                "Review Status": "Reviewing",
            },
        },
        {
            "id": "rec_approved",
            "fields": {
                "Company": "Approved Corp",
                "Review Status": "Qualified",
                "Applicable Routes": [
                    "Shiftr",
                ],
            },
        },
        {
            "id": "rec_rejected",
            "fields": {
                "Company": "Rejected Corp",
                "Review Status": "Rejected",
            },
        },
    ]

    with patch(
        "lead_engine.airtable_approval.list_records",
        return_value=records,
    ):
        result = fetch_approval_candidates()

    assert {
        item["record_id"]
        for item in result
    } == {
        "rec_reviewing",
        "rec_approved",
        "rec_rejected",
    }
