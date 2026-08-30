from unittest.mock import MagicMock

from .scheduler import LeadScheduler
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
    assert result["failed"][0]["error"] == "source unavailable"
    assert runner.run_source.call_count == 2
