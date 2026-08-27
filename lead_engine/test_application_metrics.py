from unittest.mock import MagicMock

from .application import LeadEngineApplication
from .config import LeadEngineConfig


def test_application_starts_with_empty_metrics(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    application = LeadEngineApplication(
        config=config
    )

    metrics = application.metrics_snapshot()

    assert metrics["sources_started"] == 0
    assert metrics["sources_completed"] == 0
    assert metrics["records_processed"] == 0


def test_application_tracks_processed_records(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    application = LeadEngineApplication(
        config=config
    )

    application.service.process_records = MagicMock(
        return_value={
            "accepted_count": 2,
            "duplicate_count": 1,
            "failed_count": 1,
        }
    )

    result = application.process_records(
        [
            {"source": "test"},
        ]
    )

    assert result["accepted_count"] == 2

    metrics = application.metrics_snapshot()

    assert metrics["records_processed"] == 4
    assert metrics["records_accepted"] == 2
    assert metrics["records_duplicate"] == 1
    assert metrics["records_failed"] == 1


def test_application_exposes_metrics_snapshot(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    application = LeadEngineApplication(
        config=config
    )

    application.metrics.increment(
        "records_synced",
        3,
    )

    result = application.metrics_snapshot()

    assert result["records_synced"] == 3
