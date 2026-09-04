from unittest.mock import MagicMock, patch

from .scheduler import LeadScheduler
from .source_definition import SourceDefinition
from .source_adapters import create_adapter
from .sources import StaticLeadSource


def test_scheduler_runs_multiple_sources():
    runner = MagicMock()

    runner.run_source.side_effect = [
        {
            "processed_count": 2,
            "failed_count": 0,
            "total": 2,
        },
        {
            "processed_count": 1,
            "failed_count": 0,
            "total": 1,
        },
    ]

    scheduler = LeadScheduler(
        runner=runner
    )

    sources = [
        StaticLeadSource([]),
        StaticLeadSource([]),
    ]

    result = scheduler.run(sources)

    assert result["source_count"] == 2
    assert result["failed_count"] == 0
    assert runner.run_source.call_count == 2


def test_scheduler_keeps_running_after_source_failure():
    runner = MagicMock()

    runner.run_source.side_effect = [
        RuntimeError("source unavailable"),
        {
            "processed_count": 1,
            "failed_count": 0,
            "total": 1,
        },
    ]

    scheduler = LeadScheduler(
        runner=runner
    )

    sources = [
        StaticLeadSource([]),
        StaticLeadSource([]),
    ]

    result = scheduler.run(sources)

    assert result["source_count"] == 2
    assert result["successful_source_count"] == 1
    assert result["failed_count"] == 1
    assert (
        result["failed"][0]["error"]
        == "source unavailable"
    )
    assert runner.run_source.call_count == 2


def test_scheduler_respects_source_poll_interval():
    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 1,
        "failed_count": 0,
        "total": 1,
    }

    definition = SourceDefinition(
        name="Hourly API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="none",
        poll_interval_seconds=3600,
    )

    source = create_adapter(
        definition=definition
    )

    scheduler = LeadScheduler(
        runner=runner
    )

    first = scheduler.run(
        [source]
    )

    second = scheduler.run(
        [source]
    )

    assert first["successful_source_count"] == 1
    assert second["successful_source_count"] == 0
    assert second["skipped_count"] == 1
    assert (
        second["skipped"][0]["reason"]
        == "not_due"
    )
    assert runner.run_source.call_count == 1


def test_scheduler_runs_source_again_when_poll_interval_expires():
    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 1,
        "failed_count": 0,
        "total": 1,
    }

    definition = SourceDefinition(
        name="Short Poll API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="none",
        poll_interval_seconds=60,
    )

    source = create_adapter(
        definition=definition
    )

    scheduler = LeadScheduler(
        runner=runner
    )

    scheduler.run(
        [source]
    )

    with patch(
        "lead_engine.scheduler.time.monotonic",
        side_effect=[
            1061.0,
            1061.0,
        ],
    ):
        scheduler._next_run_at[
            scheduler._source_key(source)
        ] = 1060.0

        result = scheduler.run(
            [source]
        )

    assert result["successful_source_count"] == 1
    assert result["skipped_count"] == 0
    assert runner.run_source.call_count == 2


def test_scheduler_static_source_runs_without_poll_interval():
    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 1,
        "failed_count": 0,
        "total": 1,
    }

    source = StaticLeadSource([])

    scheduler = LeadScheduler(
        runner=runner
    )

    scheduler.run(
        [source]
    )

    scheduler.run(
        [source]
    )

    assert runner.run_source.call_count == 2


def test_scheduler_persists_source_poll_interval():
    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 1,
        "failed_count": 0,
        "total": 1,
    }

    definition = SourceDefinition(
        name="Persistent Poll API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="none",
        poll_interval_seconds=3600,
    )

    source = create_adapter(
        definition=definition
    )

    scheduler = LeadScheduler(
        runner=runner
    )

    with patch(
        "lead_engine.scheduler.time.time",
        return_value=1000.0,
    ):
        first = scheduler.run(
            [source]
        )

    assert first["successful_source_count"] == 1

    runner.run_source.reset_mock()

    second_scheduler = LeadScheduler(
        runner=runner
    )

    with patch(
        "lead_engine.scheduler.time.time",
        return_value=1001.0,
    ):
        second = second_scheduler.run(
            [source]
        )

    assert second["successful_source_count"] == 0
    assert second["skipped_count"] == 1
    assert (
        second["skipped"][0]["reason"]
        == "not_due"
    )
    assert runner.run_source.call_count == 0


def test_scheduler_persisted_poll_interval_expires():
    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 1,
        "failed_count": 0,
        "total": 1,
    }

    definition = SourceDefinition(
        name="Expiring Persistent Poll API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="none",
        poll_interval_seconds=60,
    )

    source = create_adapter(
        definition=definition
    )

    scheduler = LeadScheduler(
        runner=runner
    )

    with patch(
        "lead_engine.scheduler.time.time",
        return_value=1000.0,
    ):
        first = scheduler.run(
            [source]
        )

    assert first["successful_source_count"] == 1

    runner.run_source.reset_mock()

    second_scheduler = LeadScheduler(
        runner=runner
    )

    with patch(
        "lead_engine.scheduler.time.time",
        return_value=1061.0,
    ):
        second = second_scheduler.run(
            [source]
        )

    assert second["successful_source_count"] == 1
    assert second["skipped_count"] == 0
    assert runner.run_source.call_count == 1
