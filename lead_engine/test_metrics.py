from .metrics import LeadEngineMetrics


def test_metrics_start_empty():
    metrics = LeadEngineMetrics()

    assert metrics.snapshot() == {
        "sources_started": 0,
        "sources_completed": 0,
        "sources_failed": 0,
        "records_processed": 0,
        "records_accepted": 0,
        "records_duplicate": 0,
        "records_failed": 0,
        "records_synced": 0,
        "records_pending": 0,
    }


def test_metrics_increment_and_get():
    metrics = LeadEngineMetrics()

    assert metrics.increment(
        "records_accepted"
    ) == 1

    assert metrics.increment(
        "records_accepted",
        2,
    ) == 3

    assert metrics.get(
        "records_accepted"
    ) == 3


def test_metrics_update_from_result():
    metrics = LeadEngineMetrics()

    metrics.update_from_result(
        {
            "accepted_count": 4,
            "duplicate_count": 2,
            "failed_count": 1,
        }
    )

    assert metrics.get(
        "records_processed"
    ) == 7

    assert metrics.get(
        "records_accepted"
    ) == 4

    assert metrics.get(
        "records_duplicate"
    ) == 2

    assert metrics.get(
        "records_failed"
    ) == 1


def test_metrics_snapshot_is_copy():
    metrics = LeadEngineMetrics()

    snapshot = metrics.snapshot()

    snapshot["records_accepted"] = 999

    assert metrics.get(
        "records_accepted"
    ) == 0


def test_metrics_can_reset():
    metrics = LeadEngineMetrics()

    metrics.increment(
        "records_processed",
        10,
    )

    metrics.reset()

    assert metrics.get(
        "records_processed"
    ) == 0
