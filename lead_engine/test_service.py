from unittest.mock import Mock

from .service import LeadEngineService


def test_service_process_records_delegates_to_runner(tmp_path):
    runner = Mock()
    runner.process.return_value = {
        "accepted_count": 2,
        "duplicate_count": 1,
        "failed_count": 0,
    }

    service = LeadEngineService(
        db=Mock(),
        runner=runner,
    )

    records = [
        {
            "source": "test",
            "source_id": "001",
            "url": "https://example.com/1",
            "company": "Example",
            "signal": "software engineer",
            "evidence": "Remote role",
        }
    ]

    result = service.process_records(records)

    assert result == {
        "accepted_count": 2,
        "duplicate_count": 1,
        "failed_count": 0,
    }

    runner.process.assert_called_once_with(records)


def test_service_run_sources_processes_every_source(tmp_path):
    runner = Mock()

    runner.run_source.side_effect = [
        {
            "accepted_count": 2,
            "duplicate_count": 0,
            "failed_count": 0,
        },
        {
            "accepted_count": 1,
            "duplicate_count": 1,
            "failed_count": 0,
        },
    ]

    service = LeadEngineService(
        db=Mock(),
        runner=runner,
    )

    source_one = Mock()
    source_two = Mock()

    result = service.run_sources(
        [
            source_one,
            source_two,
        ]
    )

    assert result["source_count"] == 2
    assert result["failed_count"] == 0

    assert result["results"] == [
        {
            "source": "Mock",
            "result": {
                "accepted_count": 2,
                "duplicate_count": 0,
                "failed_count": 0,
            },
        },
        {
            "source": "Mock",
            "result": {
                "accepted_count": 1,
                "duplicate_count": 1,
                "failed_count": 0,
            },
        },
    ]

    assert runner.run_source.call_count == 2


def test_service_run_sources_isolates_source_failure(tmp_path):
    runner = Mock()

    runner.run_source.side_effect = [
        RuntimeError("source unavailable"),
        {
            "accepted_count": 3,
            "duplicate_count": 1,
            "failed_count": 0,
        },
    ]

    service = LeadEngineService(
        db=Mock(),
        runner=runner,
    )

    source_one = Mock()
    source_two = Mock()

    result = service.run_sources(
        [
            source_one,
            source_two,
        ]
    )

    assert result["source_count"] == 2
    assert result["failed_count"] == 1

    assert result["results"][0] == {
        "source": "Mock",
        "result": {
            "accepted_count": 0,
            "duplicate_count": 0,
            "failed_count": 1,
            "error": "source unavailable",
        },
    }

    assert result["results"][1] == {
        "source": "Mock",
        "result": {
            "accepted_count": 3,
            "duplicate_count": 1,
            "failed_count": 0,
        },
    }

    assert runner.run_source.call_count == 2


def test_service_default_runner_is_created(tmp_path):
    service = LeadEngineService(
        db=Mock(),
    )

    assert service.runner is not None
    assert service.runner.__class__.__name__ == "SourceRunner"


def test_service_work_queue_uses_default_limit(tmp_path):
    db = Mock()

    service = LeadEngineService(
        db=db,
        runner=Mock(),
        work_queue_limit=25,
    )

    assert service.work_queue_limit == 25


def test_service_outreach_summary_returns_queue_summary(tmp_path):
    db = Mock()

    service = LeadEngineService(
        db=db,
        runner=Mock(),
    )

    leads = [
        {
            "fingerprint": "lead-001",
            "company": "Example Corp",
            "signal": "remote software engineer",
        }
    ]

    result = service.outreach_summary(leads)

    assert isinstance(result, dict)
